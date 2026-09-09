# /opt/networkat_sdwan/core/web_app/utils/email.py
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app

def _get_smtp_config():
    try:
        smtp_server = current_app.config.get("MAIL_SERVER")
        smtp_port = current_app.config.get("MAIL_PORT")
        smtp_username = current_app.config.get("MAIL_USERNAME")
        smtp_password = current_app.config.get("MAIL_PASSWORD")
    except Exception:
        smtp_server = None
        smtp_port = None
        smtp_username = None
        smtp_password = None

    if not smtp_server:
        smtp_server = os.getenv("MAIL_SERVER", "premium155.web-hosting.com")
    if not smtp_port:
        smtp_port = int(os.getenv("MAIL_PORT", 587))
    else:
        smtp_port = int(smtp_port)
    if not smtp_username:
        smtp_username = os.getenv("MAIL_USERNAME", "no_reply@networkat.net")
    if not smtp_password:
        smtp_password = os.getenv("MAIL_PASSWORD", "bePositive\"2006\"")

    return smtp_server, smtp_port, smtp_username, smtp_password


def send_verification_email(to_email, code):
    """
    Sends an account registration verification code email using SMTP configuration.
    """
    smtp_server, smtp_port, smtp_username, smtp_password = _get_smtp_config()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Verify your email - Networkat"
    msg["From"] = f"Networkat <{smtp_username}>"
    msg["To"] = to_email

    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f6f8; padding: 20px; margin: 0;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; border: 1px solid #e1e4e8;">
          <div style="background-color: #0078d4; padding: 25px; text-align: center; color: #ffffff;">
            <h1 style="margin: 0; font-size: 24px; font-weight: bold;">Networkat</h1>
          </div>
          <div style="padding: 30px; color: #1e2a41;">
            <h2 style="margin-top: 0; color: #1e2a41;">Confirm Your Email Address</h2>
            <p style="font-size: 16px; line-height: 1.5; color: #5e6c84;">Thank you for registering. Please use the verification code below to verify your email address. This code will expire in 10 minutes.</p>
            <div style="text-align: center; margin: 30px 0;">
              <span style="display: inline-block; font-size: 32px; font-weight: bold; color: #0078d4; background-color: #f0f7ff; padding: 15px 30px; border-radius: 6px; border: 1px dashed #0078d4; letter-spacing: 5px;">{code}</span>
            </div>
            <p style="font-size: 14px; color: #7a8b9e; line-height: 1.5;">If you did not request this code, you can safely ignore this email.</p>
          </div>
          <div style="background-color: #fafbfc; padding: 20px; text-align: center; font-size: 12px; color: #7a8b9e; border-top: 1px solid #f0f2f4;">
            © 2026 Networkat. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.sendmail(smtp_username, to_email, msg.as_string())
        server.quit()
        return True, None
    except Exception as e:
        return False, str(e)


def send_password_reset_email(to_email, code):
    """
    Sends a password reset code email using SMTP configuration.
    """
    smtp_server, smtp_port, smtp_username, smtp_password = _get_smtp_config()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset Your Password - Networkat"
    msg["From"] = f"Networkat <{smtp_username}>"
    msg["To"] = to_email

    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f6f8; padding: 20px; margin: 0;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; border: 1px solid #e1e4e8;">
          <div style="background-color: #0078d4; padding: 25px; text-align: center; color: #ffffff;">
            <h1 style="margin: 0; font-size: 24px; font-weight: bold;">Networkat</h1>
          </div>
          <div style="padding: 30px; color: #1e2a41;">
            <h2 style="margin-top: 0; color: #1e2a41;">Password Reset Request</h2>
            <p style="font-size: 16px; line-height: 1.5; color: #5e6c84;">We received a request to reset your Networkat account password. Please use the verification code below to set a new password. This code will expire in 10 minutes.</p>
            <div style="text-align: center; margin: 30px 0;">
              <span style="display: inline-block; font-size: 32px; font-weight: bold; color: #0078d4; background-color: #f0f7ff; padding: 15px 30px; border-radius: 6px; border: 1px dashed #0078d4; letter-spacing: 5px;">{code}</span>
            </div>
            <p style="font-size: 14px; color: #7a8b9e; line-height: 1.5;">If you did not request a password reset, please ignore this email and your password will remain unchanged.</p>
          </div>
          <div style="background-color: #fafbfc; padding: 20px; text-align: center; font-size: 12px; color: #7a8b9e; border-top: 1px solid #f0f2f4;">
            © 2026 Networkat. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.sendmail(smtp_username, to_email, msg.as_string())
        server.quit()
        return True, None
    except Exception as e:
        return False, str(e)


def send_renewal_reminder_email(to_email, client_name, renewal_date, plan_name="Standard"):
    """
    Sends a subscription renewal reminder email 3 days before renewal_date.
    """
    smtp_server, smtp_port, smtp_username, smtp_password = _get_smtp_config()

    date_str = renewal_date.strftime("%Y-%m-%d") if hasattr(renewal_date, "strftime") else str(renewal_date)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Action Required: Your Networkat Subscription Renews on {date_str}"
    msg["From"] = f"Networkat <{smtp_username}>"
    msg["To"] = to_email

    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f6f8; padding: 20px; margin: 0;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; border: 1px solid #e1e4e8;">
          <div style="background-color: #0078d4; padding: 25px; text-align: center; color: #ffffff;">
            <h1 style="margin: 0; font-size: 24px; font-weight: bold;">Networkat SD-WAN</h1>
          </div>
          <div style="padding: 30px; color: #1e2a41;">
            <h2 style="margin-top: 0; color: #1e2a41;">Subscription Renewal Notice</h2>
            <p style="font-size: 16px; line-height: 1.5; color: #5e6c84;">
              Dear <strong>{client_name}</strong>,
            </p>
            <p style="font-size: 15px; line-height: 1.5; color: #5e6c84;">
              This is a friendly reminder that your <strong>{plan_name.title()}</strong> plan subscription is scheduled for renewal on:
            </p>
            <div style="text-align: center; margin: 25px 0;">
              <span style="display: inline-block; font-size: 24px; font-weight: bold; color: #0078d4; background-color: #f0f7ff; padding: 12px 28px; border-radius: 6px; border: 1px dashed #0078d4;">
                {date_str}
              </span>
            </div>
            <p style="font-size: 14px; line-height: 1.5; color: #5e6c84;">
              To ensure uninterrupted SD-WAN mesh connectivity and device provisioning, please make sure your account is renewed before the expiration date.
            </p>
            <p style="font-size: 13px; color: #7a8b9e; line-height: 1.5;">
              If you have already renewed, you can safely disregard this message.
            </p>
          </div>
          <div style="background-color: #fafbfc; padding: 20px; text-align: center; font-size: 12px; color: #7a8b9e; border-top: 1px solid #f0f2f4;">
            © 2026 Networkat. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.sendmail(smtp_username, to_email, msg.as_string())
        server.quit()
        return True, None
    except Exception as e:
        return False, str(e)

