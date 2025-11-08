import streamlit as st
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email_report(recipient_email: str, flagged_files_log: list):
    """
    Connects to the SMTP server and sends a report to the user.
    Returns None on success, or an error_message string on failure.
    """
    try:
        # Get sender credentials from secrets
        sender_email = st.secrets["SENDER_EMAIL"]
        sender_password = st.secrets["SENDER_PASSWORD"]

        if not sender_email or not sender_password:
            # Return the error message instead of calling st.error
            return "Sender email credentials are not set in secrets.toml."

        # Create the email message
        message = MIMEMultipart("alternative")
        message["Subject"] = "Invoice Batch Processing Report"
        message["From"] = sender_email
        message["To"] = recipient_email

        # Create the email body
        text_body = "Your invoice batch has been processed. See the summary of flagged files below:\n\n"
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: sans-serif; line-height: 1.6; }}
                h2 {{ color: #5D9CEC; }}
                .container {{ width: 90%; margin: auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
                .file {{ background-color: #f9f9f9; border-left: 5px solid #E74C3C; padding: 10px; margin-bottom: 10px; }}
                .reason {{ margin-left: 20px; font-style: italic; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Invoice Batch Report</h2>
                <p>Your invoice batch has finished processing. The following {len(flagged_files_log)} files were flagged for review:</p>
                <hr>
        """

        for item in flagged_files_log:
            file_name = item['file_name']
            reasons = item['reasons']
            
            text_body += f"File: {file_name}\n"
            html_body += f"<div class='file'><strong>File: {file_name}</strong><br>"
            
            for reason in reasons:
                text_body += f"  - {reason}\n"
                html_body += f"<div class='reason'>- {reason}</div>"
            
            text_body += "\n"
            html_body += "</div>"

        html_body += "</div></body></html>"

        message.attach(MIMEText(text_body, "plain"))
        message.attach(MIMEText(html_body, "html"))

        # Connect to Gmail's SMTP server
        # This is where your "intentionally wrong input" will cause an exception
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, message.as_string())
        
        # If we get here, it worked. Return None for success.
        return None

    except Exception as e:
        # If *anything* goes wrong, return the error message as a string
        return f"Failed to send email report: {e}"