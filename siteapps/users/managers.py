import logging
from smtplib import SMTPException
import uuid

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _


def send_welcome_email(user, password_generated):
    """Send welcome email to user"""
    logging.info("Sending welcome email..")
    is_staging = "staging" in settings.WSGI_APPLICATION
    subject = "Welcome to WildePod staging!" if is_staging else "Welcome to WildePod!"
    context = {"user": user, "password_generated": password_generated, "is_staging": is_staging}
    html_message = render_to_string("account/email/welcome.html", context)
    plain_message = strip_tags(html_message)
    try:
        send_mail(
            subject,
            plain_message,
            "WildePod Admin <noreply@wildepod.org>",
            [user.email],
            html_message=html_message,
            fail_silently=False,
        )
    except SMTPException as e:
        logging.error(f"Error sending welcome email. Error msg - {e}")


# Code copied from https://testdriven.io/blog/django-custom-user-model/
class UserManager(BaseUserManager):
    """
    Custom user model manager where email is the unique identifiers
    for authentication instead of usernames.
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """
        Create and save a User with the given email and password.
        """
        if not email:
            raise ValueError(_("The Email must be set"))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        # If the password field is None, generate a password and send it in the email
        password_generated = None if password else uuid.uuid4().hex[:12]
        password = password if password else password_generated
        user.set_password(password)
        user.save(using=self._db)
        logging.info("User created successfully!")
        # TODO: This might not be ideal when sign up is opened up to regular users since it bypasses the verification process
        # Create an email address for django all auth and set it to verified & primary
        # This only happens when users are created programmatically since sign up is disabled
        EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
        logging.info("Email address created successfully!")
        send_welcome_email(user, password_generated)

        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        logging.info("Creating regular user..")
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_active", True)

        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """
        Create and save a SuperUser with the given email and password.
        """
        logging.info("Creating super user..")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_volunteer", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        return self._create_user(email, password, **extra_fields)
