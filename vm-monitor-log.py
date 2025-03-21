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

#Azure Constants
AZURE_VARS = {
    "SUBSCRIPTION_ID"           : os.getenv("SUBSCRIPTION_ID"),
    "LOGS_WORKSPACE_ID"         : os.getenv("LOGS_WORKSPACE_ID"),
    "LOGS_WORKSPACE_KEY"        : os.getenv("LOGS_WORKSPACE_KEY"),
    "LOGS_API_ENDPOINT_REGION"  : os.getenv("LOGS_API_ENDPOINT_REGION"),
    "CLIENT_ID"                 : os.getenv("CLIENT_ID"),
    "TENANT_ID"                 : os.getenv("TENANT_ID"),
    "CLIENT_SECRET"             : os.getenv("CLIENT_SECRET")
}

#Freshdesk API Constants
FRESHDESK_CREDENTIALS = {
    "FRESHDESK_API_KEY"         : os.getenv("API_KEY"),
    "FRESHDESK_DOMAIN"          : os.getenv("FRESHDESK_DOMAIN")
}

#SMTP Constants 
SMTP_CREDENTIALS = {
    "SMTP_LOGIN"                : os.getenv("SMTP_LOGIN"),
    "SMTP_PASSWORD"             : os.getenv("SMTP_PASSWORD"),
    "SMTP_SERVER"               : os.getenv("SMTP_SERVER"),
    "SMTP_PORT"                 : os.getenv("SMTP_PORT"),
    "SMTP_DOMAIN"               : os.getenv("SMTP_DOMAIN")
}

messaging_metadata = {
    "sender_name"               : os.getenv("sender_name"),
    "recipient_email"           : os.getenv("recipient_email"),
    "recipient_name"            : os.getenv("recipient_name"),
    "sender_email"              : f"notifications{SMTP_CREDENTIALS['SMTP_DOMAIN']}"
}

service_allocation_data = {
    "resource_group"            : os.getenv("resource_group"),
    "virtual_machine"           : os.getenv("virtual_machine")
}

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
            create_freshdesk_ticket(custom_message, "Log number generation")
            print(custom_message)
        
    return wrapper

def service_principal_authentication() -> ComputeManagementClient:
    """Checks the Authentication of Azure's Service Principal"""
    
    custom_message = None

    try:
        credentials = ClientSecretCredential(
            
            tenant_id       =   AZURE_VARS["TENANT_ID"], 
            client_id       =   AZURE_VARS["CLIENT_ID"], 
            client_secret   =   AZURE_VARS["CLIENT_SECRET"] 

        )
 
        return ComputeManagementClient(credentials, AZURE_VARS["SUBSCRIPTION_ID"])

    except Exception as e:
        custom_message = f"There was an error in authenticating the Service Principal {e}"

    if custom_message:
        create_freshdesk_ticket(custom_message, "Service Principal Authentication")
        print(custom_message)

def create_freshdesk_ticket(exception_or_error_message:str, custom_subject:str, group_id:int = 201000039106, responder_id:int = 201002411183) -> int:
    """
    Creates a Freshdesk ticket on behalf of the end user. This will be sent straight to the users inbox, where the user can add further information if they need to/
    
    This function must be called within a function which utulizes the assign_log_number decorator.

    This function will only be called when an exception is thrown. The exception message will be passed to the 'exception' parameter.
    """
    
    API_URL = f'https://{FRESHDESK_CREDENTIALS["FRESHDESK_DOMAIN"]}.freshdesk.com/api/v2/tickets/'

    description = f"This support ticket has been automatically generated because of the following error or exception message {exception_or_error_message}."

    ticket_data = {
        "subject"     : custom_subject,
        "description" : description, 
        'priority'    : 1,
        'status'      : 2,
        'group_id'    : group_id,
        'responder_id': responder_id,
        'requester'   : {
            'name'    : messaging_metadata["recipient_name"],
            'email'   : messaging_metadata["recipient_email"] 
        } 
    }

    custom_message  = None
    ticket_id       = None
    
    try:
        response = requests.post(
            API_URL,
            auth    = (FRESHDESK_CREDENTIALS["FRESHDESK_API_KEY"], 'X'),
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
                custom_message = f"A support ticket under the reference {ticket_id} has been created. You can view your outstanding support tickets by logging into your Freshdesk account. This will be due by {due_by}."

        elif response.status_code == 429:
            custom_message = f"API request limit exceeded: {response.status_code}"
        
        else:
            custom_message = f"Support Ticket Creation Error. Error code: {response.status_code} Error HTTP response: {response.text} Error response {response.content}"

    if custom_message:
        print(custom_message)

    return ticket_id

def send_notification(custom_message: str,) -> None:
    """Sends a notification to the address specificed in the 'receiver_name' parameter, which will pass a custom message to the 'message_body' module.
    """
    msg             = MIMEMultipart()
    msg['Subject']  = f"System Degradation Alert | {service_allocation_data['virtual_machine']}"
    msg['From']     = f'"{messaging_metadata["sender_name"]}" <{messaging_metadata["sender_email"]}>'
    msg['To']       = messaging_metadata["recipient_email"]
    body            = MIMEText(message_body(custom_message), 'html')
    msg.attach(body)
    
    try:
        with smtplib.SMTP(SMTP_CREDENTIALS["SMTP_SERVER"], SMTP_CREDENTIALS["SMTP_PORT"]) as server:
            server.starttls()
            server.login(SMTP_CREDENTIALS["SMTP_LOGIN"], SMTP_CREDENTIALS["SMTP_PASSWORD"])
            server.sendmail(messaging_metadata["sender_email"], messaging_metadata["recipient_email"], msg.as_string())
    except Exception as e:
        custom_subject = "Message Dispatch Issue"
        print(f"custom_message - {e}")
        create_freshdesk_ticket(e, custom_subject)

@assign_log_number
def message_body(custom_message: str, assign_log_number:str = None) -> str:
    """
    Defines the HTML email body of the message, complete with the name of the sender,
    the name of the receiver, 
    the incident number reference and the new status of the VM.
    
    It will also generate a support ticket to be send to Freshdesk, 
    is a ticket number is returned, 
    a ticket number was successful in being generated. 
    This this is not the case, it will return a message informing the end user that a ticket was unable to be generated. 
    
    This is to be incorporated in the 'send_notification' method & attached to the MIMEMultipart()
    """

    resource_data_table = f"""
        <table border="0" cellpadding="5" cellspacing="0" style="border-collapse: collapse; text-align: left;">
            <tr>
                <th>Incident Number:</th>
                <td>{assign_log_number}</td>
            </tr>
            <tr>
                <th>VM Name:</th>
                <td>{service_allocation_data['virtual_machine']}</td>
            </tr>
            <tr>
                <th>Resource Group:</th>
                <td>{service_allocation_data['resource_group']}</td>
            </tr>
            <tr>
                <th>Comment:</th>
                <td>{custom_message}</td>
            </tr>
        </table>
    """
    
    return  f"""Dear {messaging_metadata['recipient_name']}<br><br>
        We are writing to you because an incident has occured during the normal operation of your VM, & we will now commence an investigation into this.<br><br>
        ======================<br>
        {resource_data_table}
        ======================<br>
        If you need further assistance, please contact us at engineering{SMTP_CREDENTIALS['SMTP_DOMAIN']}.<br><br>
        Yours sincerely<br>
        <b>{messaging_metadata['sender_name']}</b><br><br>
        """

def get_vm_status(compute_client) -> None:
    """Retrieve the current status of the VM."""
    
    custom_message = None

    try:
        # Explicitly request the instance view
        vm = compute_client.virtual_machines.get(service_allocation_data["resource_group"], service_allocation_data["virtual_machine"], expand='instanceView')
        
        # Check if instance view is available
        if vm.instance_view:
            return vm.instance_view.statuses[1].code  
        else:
            
            custom_message = f"There was an error in the retrieval of the VM instance. No further information is available."

    except Exception as e:
        
        custom_message = f"There was an error in the retrieval of the status of your VM - {e} ."

    if custom_message:
        custom_subject = "Error with Obtaining VM Status"
        create_freshdesk_ticket(custom_message, custom_subject)
        print(custom_message)

    return

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

@assign_log_number
def log_to_azure_monitor(new_vm_status:str, assign_log_number:str = None) -> None:
    """Logs the incident data to Azure Monitor via HTTP Data Collector API.
    Disgreard Log Number data"""
    
    log_data = [{
        "TimeGenerated"     : datetime.now(timezone.utc).isoformat(),
        "VMName"            : service_allocation_data["virtual_machine"],
        "VMStatus"          : new_vm_status,
        "LogNumber"         : assign_log_number,
    }]
    
    # Convert log data to JSON format
    body = json.dumps(log_data)

    # Generate the headers with the signature
    headers = generate_authentication_signature(AZURE_VARS["LOGS_WORKSPACE_ID"], AZURE_VARS["LOGS_WORKSPACE_KEY"], body)

    LOGS_API_ENDPOINT = f"https://{AZURE_VARS['LOGS_WORKSPACE_ID']}.ods.opinsights.azure.com/api/logs?api-version=2016-04-01"
    
    custom_message = None

    try:
        
        response = requests.post(LOGS_API_ENDPOINT, headers=headers, data=body)
        
        if response.status_code == 200:

            custom_message = f"There is a degradation status to your VM {service_allocation_data['virtual_machine']} from resource group {service_allocation_data['resource_group']}. Status {new_vm_status}"
        
        else:

            custom_message = f"There was an error logging to Azure. Logging error {response.status_code}, Response: {response.text}"

    except Exception as e:

        custom_message = f"There was an error in the request retrieval - {e}"

    if custom_message:
        custom_subject = "Logging to Azure Monitoring System"
        create_freshdesk_ticket(custom_message, custom_subject)
        print(custom_message)

    return

def main() -> None:
    
    previous_vm_status = "PowerState/running"  
    is_shutdown_logged = False
    
    while True:
        
        compute_client = service_principal_authentication()
        current_vm_status = get_vm_status(compute_client)
        
        if current_vm_status != previous_vm_status:
            if current_vm_status != "PowerState/running" and not is_shutdown_logged:
                log_to_azure_monitor(current_vm_status)
                is_shutdown_logged = True 
            
            if current_vm_status == "PowerState/running":
                is_shutdown_logged = False

        previous_vm_status = current_vm_status
        
        time.sleep(300)  # Pause for 5 minutes between checks

if __name__ == "__main__":
    main()
