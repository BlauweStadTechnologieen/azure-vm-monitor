import time
import smtplib
import json
import base64
import hashlib
import hmac
import requests
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from azure.mgmt.compute import ComputeManagementClient
from azure.identity import ClientSecretCredential
from functools import wraps
import os
from dotenv import load_dotenv

load_dotenv()

# Azure subscription
SUBSCRIPTION_ID             =   os.getenv("SUBSCRIPTION_ID")

# Azure Resources
resource_group_name         =   'VMs'  
vm_name                     =   'SynergexSystems'

# Logs Workspace Information
LOGS_WORKSPACE_ID           =   os.getenv("LOGS_WORKSPACE_ID")
LOGS_WORKSPACE_KEY          =   os.getenv("LOGS_WORKSPACE_KEY")  
LOGS_API_ENDPOINT_REGION    =   os.getenv("LOGS_API_ENDPOINT_REGION")

# Data Collection Endpoint
DATA_COLLECTION_ENDPOINT    =   f"https://vmstatusdce-o0w0.{LOGS_API_ENDPOINT_REGION}-1.ingest.monitor.azure.com"

# Email setup
sender_name                 =   'Blue City Capital Technologies, Inc'
sender_email                =   'notifications@bluecitycapital.com' 
receiver_name               =   'Synergex Systems'
receiver_email              =   f'{receiver_name} <todd.gilbey@synergex-systems.com>' 


def execution_trace(func) -> str:
    """Collects the name of the function where the issue, error or degradation resides."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        calling_function = f"Source: def {func.__name__}()"
        try:
            return func(*args, **kwargs, calling_function = calling_function)
        except Exception as e:
            print(f"There was an error in returning the name of the function. Logs available {e}")
    return wrapper

def assign_log_number(func) -> str:
    """Generates a log reference number, which will be sent to Azure Monitor portal."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        assign_log_number = generate_incident_reference_number()
        
        custom_message = None
        
        try:
            return func(*args, **kwargs, assign_log_number = assign_log_number) 
        
        except TypeError as e:
            custom_message = f"There was a TypeError Exception associated with assigning the Azure log number {e}"

        except Exception as e:
            custom_message = f"There was an error in generating a log reference. Logs available {e}"

        if custom_message:
            print(custom_message)
        
    return wrapper

# Azure Authentication
@execution_trace
@assign_log_number
def service_principal_authentication(calling_function:str = None, assign_log_number = None) -> ComputeManagementClient:
    """Checks the Authentication of Azure's Service Principal"""
    
    custom_message = None

    try:
        credentials = ClientSecretCredential(
            
            client_id           =   os.getenv("CLIENT_ID"), # Retrieved from environment variable
            tenant_id           =   os.getenv("TENANT_ID"), # Retrieved from environment variable
            client_secret       =   os.getenv("CLIENT_SECRET") # Retrieved from environment variable

        )

        return ComputeManagementClient(credentials, SUBSCRIPTION_ID)

    except Exception as e:
        custom_message = f"There was an error in authenticating the Service Principal {e} | {calling_function}."

    if custom_message:
        send_notification(custom_message, sender_name, receiver_name, assign_log_number)
        print(custom_message)

def message_body(custom_message: str, sender_name: str, receiver_name:str, incident_number:str) -> str:
    """
    Defines the HTML email body of the message, complete with the name of the sender, the name of the receiver, the incident number reference and the new status of the VM.
    
    It will also generate a support ticket to be send to Freshdesk, is a ticket number is returned, a ticket number was successful in being generated. This this is not the case, it will return a message informing the end user that a ticket was unable to be generated. 
    
    This is to be incorporated in the 'send_notification' method & attached to the MIMEMultipart()
    """

    was_ticket_id_generated = create_freshdesk_ticket(incident_number,custom_message)

    ticket_return_message = (
        "A support ticket was generated. You should receive this shortly."
        if was_ticket_id_generated is not None
        else "Apologies, but we encountered an internal technical issue that prevented the creation of a support ticket. You can still reach out to us by referencing the incident log number provided below. Thank you for your understanding and cooperation."
    )

    ticket_id           =   was_ticket_id_generated if was_ticket_id_generated is not None else "No ticket ID was generated at this time."
    helpdesk_contact    =   'hello@bluecitycapital.com'

    resource_data_table = f"""
        <table border="0" cellpadding="5" cellspacing="0" style="border-collapse: collapse; text-align: left;">
            <tr>
                <th>Incident Number:</th>
                <td>{incident_number}</td>
            </tr>
            <tr>
                <th>VM Name:</th>
                <td>{vm_name}</td>
            </tr>
            <tr>
                <th>Resource Group Name:</th>
                <td>{resource_group_name}</td>
            </tr>
            <tr>
                <th>Support Ticket ID:</th>
                <td>{ticket_id}</td>
            </tr>
            <tr>
                <th>Comment:</th>
                <td>{custom_message}</td>
            </tr>
        </table>
    """
    
    return  f"""Dear {receiver_name}<br><br>
        We are writing to you because an incident has occured during the normal operation of your VM, & we will now commence an investigation into this.<br><br>
        {ticket_return_message}<br><br>
        ======================<br>
        {resource_data_table}
        ======================<br>
        If you need further assistance, please contact us at {helpdesk_contact}.<br><br>
        Yours sincerely<br>
        {sender_name}<br><br>
        """

def create_freshdesk_ticket(logging_incident_number:str, exception_or_error_message:str, group_id:int = 201000039106, responder_id:int = 201002411183, subject:str = "Github is a true Git sometimes!") -> int:
    """
    Creates a Freshdesk ticket on behalf of the end user. This will be sent straight to the users inbox, where the user can add further information if they need to/
    
    This function must be called within a function which utulizes the assign_log_number decorator.

    This function will only be called when an exception is thrown. The exception message will be passed to the 'exception' parameter.
    """
    
    FRESHDESK_DOMAIN    = os.getenv("FRESHDESK_DOMAIN")
    API_KEY             = os.getenv("API_KEY")
    API_URL             = f'https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/tickets/'

    description = f"This support ticket has been automatically generated because of the following error or exception message {exception_or_error_message}. Log number {logging_incident_number}"

    ticket_data = {
        "subject"     : subject,
        "description" : description, 
        'priority'    : 1,
        'status'      : 2,
        'group_id'    : group_id,
        'responder_id': responder_id,
        'requester'   : {
            'name'    : receiver_name,
            'email'   : receiver_email  
        } 
    }

    custom_message  = None
    ticket_id       = None
    
    try:
        response = requests.post(
            API_URL,
            auth    = (API_KEY, 'X'),
            json    = json.dumps(ticket_data),
            timeout = 30,
            headers = {'Content-Type' : 'application/json'}
        )

    except TypeError as e:
        custom_message = f"Type Error Exception: {e}"
    
    except response.RequestException as e:
        custom_message = f"Requests Exception: {e}"

    except Exception as e:
        custom_message = f"General Exception: {e}"

    else:
    
        if response.status_code == 201:
            
            ticket_info = response.json
            ticket_id   = ticket_info.get("id")
            due_by      = ticket_info.get("due_by")

            if ticket_id:
                custom_message = f"A support ticket under the reference {ticket_id} has been created. You can view your outstanding support tickets by logging into your Freshdesk account under your login email {receiver_email}. This will be due by {due_by}."

        elif response.status_code == 429:
            custom_message = f"API request limit exceeded: {response.status_code}"
        
        else:
            custom_message = f"Support Ticket Creation Error. Error code: {response.status_code} Error HTTP response: {response.text} Error response {response.content}"

    if custom_message:
        print(custom_message)
        print(logging_incident_number)

    return ticket_id

@execution_trace
def send_notification(custom_message: str,sender_name:str, receiver_name:str, incident_number:str, calling_function:str = None) -> None:
    """Sends a notification to the address specificed in the 'receiver_name' parameter, which will pass a custom message to the 'message_body' module.
    """
    msg             = MIMEMultipart()
    msg['Subject']  = f"System Degradation Alert | {vm_name}"
    msg['From']     = f'"{sender_name}" <{sender_email}>'
    msg['To']       = receiver_email
    body            = MIMEText(message_body(custom_message, sender_name, receiver_name, incident_number), 'html')
    msg.attach(body)

    try:
        with smtplib.SMTP(os.getenv("SMTP_SERVER"), os.getenv("SMTP_PORT")) as server:
            server.starttls()
            server.login(os.getenv("SMTP_LOGIN"), os.getenv("SMTP_PASSWORD"))
            server.sendmail(sender_email, receiver_email, msg.as_string())
    except Exception as e:
        print(f"{e}. {calling_function}")

@execution_trace
@assign_log_number
def get_vm_status(compute_client, calling_function:str = None, assign_log_number:str = None) -> str:
    """Retrieve the current status of the VM."""
    
    custom_message = None

    try:
        # Explicitly request the instance view
        vm = compute_client.virtual_machines.get(resource_group_name, vm_name, expand='instanceView')
        
        # Check if instance view is available
        if vm.instance_view:
            return vm.instance_view.statuses[1].code  
        else:
            
            custom_message = f"There was an error in the retrieval of the VM instance. No further information is available."

    except Exception as e:
        
        custom_message   =   f"There was an error in the retrieval of the status of your VM. Full error logging is available: {e} ."

    if custom_message:
        send_notification(custom_message, sender_name, receiver_name, assign_log_number)
        print(custom_message)

    return custom_message

def generate_incident_reference_number() -> str:
    """Generate an incident reference number to be logged in the Azure monitoring logs, using Python's built-in UUID module. UUID4 is applied."""
    
    """Generates a universally unique identifier (UUID) to be used as a log number. UUID version 4 is used."""
    return f"{uuid.uuid4()}"

def generate_authentication_signature(workspace_id:str, workspace_key:str, body) -> list[str,str]:
    """Generates the signature needed for authenticating the request."""
    
    date            = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
    content_length  = str(len(body))

    # Prepare the string to sign
    string_to_sign  = f"POST\n{content_length}\napplication/json\nx-ms-date:{date}\n/api/logs"

    # Generate the signature using HMAC and SHA256
    signature = base64.b64encode(
        hmac.new(
            base64.b64decode(workspace_key),
            string_to_sign.encode('utf-8'),
            hashlib.sha256
        ).digest()
    ).decode('utf-8')

    # Prepare the request headers
    headers = {
        "Content-Type"  : "application/json",
        "Authorization" : f"SharedKey {workspace_id}:{signature}",
        "x-ms-date"     : date,
        "Log-Type"      : "CustomLogs" 
    }

    return headers

@execution_trace
@assign_log_number
def log_to_azure_monitor(new_vm_status:str, calling_function:str = None, assign_log_number:str = None) -> None:
    """Logs the incident data to Azure Monitor via HTTP Data Collector API.
    Disgreard Log Number data"""

    log_data = [{
        "TimeGenerated"     : datetime.now(timezone.utc).isoformat(),
        "VMName"            : vm_name,
        "VMStatus"          : new_vm_status,
        "LogNumber"         : assign_log_number,
    }]
    
    # Convert log data to JSON format
    body                = json.dumps(log_data)

    # Generate the headers with the signature
    headers             = generate_authentication_signature(LOGS_WORKSPACE_ID, LOGS_WORKSPACE_KEY, body)

    # Azure Monitor HTTP API endpoint
    LOGS_API_ENDPOINT   = f"https://{LOGS_WORKSPACE_ID}.ods.opinsights.azure.com/api/logs?api-version=2016-04-01"

    # Send the POST request to the Azure Monitor API

    custom_message = None

    try:
        response = requests.post(LOGS_API_ENDPOINT, headers=headers, data=body)
        
        if response.status_code == 200:
            
            custom_message = f"There is a new status to the VM {vm_name}: {new_vm_status}."

        else:

            custom_message = f"There was an error logging to Azure. Logging error {response.status_code}, Response: {response.text}"

    except Exception as e:

        custom_message = f"There was an error in the request retrieval. Logs available: {e}"

    if custom_message:
        send_notification(custom_message,sender_name,receiver_name,assign_log_number)
        print(custom_message)

    return

def main() -> None:
    
    previous_vm_status = "PowerState/running"

    while True:
        compute_client      = service_principal_authentication()
        current_vm_status   = get_vm_status(compute_client)

        if current_vm_status != previous_vm_status:
            log_to_azure_monitor(current_vm_status)
        previous_vm_status = current_vm_status
        time.sleep(300)

if __name__ == "__main__":
    main()
