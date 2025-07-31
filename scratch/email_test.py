"""
Simple email test script based on send_welcome_email function
Run with: python manage.py shell < scratch/email_test.py
"""
import logging
from smtplib import SMTPException
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

def test_send_email(recipient_email, test_name="Test User"):
    """Send test welcome email"""
    logging.info("Sending test email..")
    
    # Check environment settings
    is_staging = "staging" in settings.WSGI_APPLICATION
    is_bhutan = "bhutan" in settings.WSGI_APPLICATION
    
    if is_staging:
        subject = "Test Email - WildePod Staging!"
    elif is_bhutan:
        subject = "Test Email - WildePod Bhutan!"
    else:
        subject = "Test Email - WildePod!"
    
    # Create a mock user object for template
    class MockUser:
        def __init__(self, email, name):
            self.email = email
            self.name = name
    
    mock_user = MockUser(recipient_email, test_name)
    password_generated = "test123456"
    
    context = {
        "user": mock_user, 
        "password_generated": password_generated, 
        "is_staging": is_staging, 
        "is_bhutan": is_bhutan
    }
    
    try:
        html_message = render_to_string("account/email/welcome.html", context)
        plain_message = strip_tags(html_message)
        from_email = "WildePod Admin <noreply@wildepod.org>"
        
        print(f"Attempting to send email to: {recipient_email}")
        print(f"Subject: {subject}")
        print(f"From: {from_email}")
        print(f"Email backend: {settings.EMAIL_BACKEND}")
        
        result = send_mail(
            subject,
            plain_message,
            from_email,
            [recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        
        print(f"✅ Email sent successfully! Result: {result}")
        logging.info(f"Test email sent successfully! Result - {result}")
        
    except SMTPException as e:
        print(f"❌ SMTP Error: {e}")
        logging.error(f"Error sending test email. Error msg - {e}")
    except Exception as e:
        print(f"❌ General Error: {e}")
        logging.error(f"Unexpected error sending test email. Error msg - {e}")

# Replace with your email address
test_email = "prabathg@gmail.com"  # UPDATE THIS
test_name = "Test User"

if test_email == "your-email@example.com":
    print("❌ Please update the test_email variable in the script with your actual email address!")
else:
    test_send_email(test_email, test_name)