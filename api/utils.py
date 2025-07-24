import os
import resend
from django.template.loader import render_to_string

resend.api_key = os.environ.get("RESEND_API_KEY")

def send_email(to: str, subject: str, template_name: str, context: dict):
    # Build the full path to the template
    template_path = os.path.join(os.path.dirname(__file__), "email_templates", template_name)

    # Read and render the template with context
    with open(template_path, "r", encoding="utf-8") as template_file:
        html_content = template_file.read()

    rendered_content = render_to_string(template_name, context)

    # Send email
    params: resend.Emails.SendParams = {
        "from": "ROME <noreply@nonamegroup.com>",  # Update with rome domain
        "to": [to],
        "subject": subject,
        "html": rendered_content,
    }
    try:
        email = resend.Emails.send(params)
        print(f"Email sent to {to}: {email}")
    except Exception as e:
        print(f"Failed to send email to {to}: {e}")
