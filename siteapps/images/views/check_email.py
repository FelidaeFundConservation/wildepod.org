import datetime
import email
import imaplib
import logging
import re
from email.header import decode_header

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http.response import JsonResponse
from django.shortcuts import render
from django.views.generic.base import View


# Fetch the Dropbox 2FA code from a dedicated email and return it to the frontend
class CheckDropbox2FAEmailView(LoginRequiredMixin, View):

    # Function to get email content part i.e its body part
    def get_body(self, msg):
        if msg.is_multipart():
            return self.get_body(msg.get_payload(0))
        else:
            return msg.get_payload(None, True)
        
    # Function to get the list of emails under this label
    def get_last_email(self, from_address, con):
        # Calculate yesterdays date and only fetch emails since then to avoid fetching too many email ids
        # (Note: IMAP doesn't let you search on a time field, otherwise we should only check for ~10 mins)
        yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
        yesterday_str = yesterday.strftime('%d-%b-%Y')

        # Search for emails matching the given criteria *and* within the last day 
        search_str = '(FROM "{}" SINCE {})'.format(from_address, yesterday_str)
        result, data = con.search(None, search_str)     
        if result == 'OK':
            message_ids = data[0].split()

            if message_ids:
                # By default, Gmail orders messages in order of which they were received. So we can fetch the last message.
                last_message_id = message_ids[0]

                typ, byte_msg = con.fetch(last_message_id, '(RFC822)')
                msg = email.message_from_bytes(byte_msg[0][1])
                # Check if the email is within the last 10 minutes
                email_time_str = decode_header(msg['Date'])[0][0]
                email_time_local = datetime.datetime.strptime(email_time_str, '%a, %d %b %Y %H:%M:%S %z').replace(tzinfo=None)
                if email_time_local > (datetime.datetime.now() - datetime.timedelta(minutes=10)):
                    return str(msg.get_payload()[0])


    def parse_email(self, msg):
        # Construct a regular expression pattern.
        # TODO: This has hardcoded text from the email and is brittle to any changes in wording. 
        pattern = r'security code.*?(\d{6}).*?We noticed'
        
        # Search for the pattern in the message
        match = re.search(pattern, msg,  re.DOTALL)
        
        # If a match is found, return the numeric code
        if match:
            return match.group(1)
        else:
            return None
    
    def post(self, request, *args, **kwargs):
        logging.info("Checking email for Dropbox 2FA code")

        imap_url = settings.EMAIL_2FA_IMAP_URL
        user = settings.EMAIL_2FA_USER
        password = settings.EMAIL_2FA_PASSWORD

        # this is done to make SSL connection with GMAIL
        con = imaplib.IMAP4_SSL(imap_url) 
        
        # logging the user in
        con.login(user, password) 
        
        # calling function to check for email under this label
        con.select('Inbox') 
        
        # fetching emails from Dropbox
        msg = self.get_last_email('no-reply@dropbox.com', con)
        if msg:
            code = self.parse_email(msg)
            if code:
                return JsonResponse({"success": True, "code": code})
        
        # Finding the required content from our msgs
        # User can make custom changes in this part to
        # fetch the required content he / she needs
        
        return JsonResponse({"success": True, "code": "NONE"})


