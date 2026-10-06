"""
Email notification service for sending meeting recaps.
Sends professional HTML emails similar to Fireflies.ai after meetings complete.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
import logging

from ..config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Handles sending meeting recap emails to participants."""

    @staticmethod
    def _format_datetime(dt: datetime) -> str:
        """Format datetime for email display."""
        return dt.strftime("%b %dth at %I:%M %p %Z")

    @staticmethod
    def _get_frontend_url() -> str:
        """Get the frontend URL from settings."""
        return getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')

    @staticmethod
    def create_meeting_recap_email(
        recipient_email: str,
        recipient_name: str,
        meeting_title: str,
        meeting_date: datetime,
        meeting_id: int,
        invited_by: Optional[str] = None
    ) -> dict:
        """
        Create a professional HTML email for meeting recap.
        
        Args:
            recipient_email: Email address to send to
            recipient_name: Name of the recipient
            meeting_title: Title of the meeting
            meeting_date: When the meeting took place
            meeting_id: Database ID for the meeting
            invited_by: Email of person who invited the bot
            
        Returns:
            dict with 'subject', 'html', and 'text' keys
        """
        frontend_url = EmailService._get_frontend_url()
        meeting_url = f"{frontend_url}/dashboard/meetings/{meeting_id}"
        formatted_date = EmailService._format_datetime(meeting_date)
        
        invited_text = f"{invited_by} invited" if invited_by else "You invited"
        
        # HTML version with styling similar to Fireflies
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #ffffff;
        }}
        .header {{
            padding: 40px 40px 20px;
            text-align: center;
        }}
        .logo {{
            font-size: 24px;
            font-weight: 700;
            color: #4f46e5;
            margin-bottom: 10px;
        }}
        .invited-by {{
            text-align: center;
            padding: 20px;
            background-color: #f9fafb;
        }}
        .invited-icon {{
            width: 80px;
            height: 80px;
            margin: 0 auto 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 40px;
        }}
        .invited-name {{
            font-size: 24px;
            font-weight: 600;
            color: #1f2937;
            margin-bottom: 8px;
        }}
        .invited-email {{
            color: #6b7280;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        .invitation-text {{
            font-size: 18px;
            color: #374151;
            margin-bottom: 10px;
        }}
        .subtitle {{
            color: #6b7280;
            font-size: 14px;
        }}
        .meeting-card {{
            margin: 30px 40px;
            padding: 30px;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            text-align: center;
        }}
        .meeting-icon {{
            width: 48px;
            height: 48px;
            margin: 0 auto 16px;
            background-color: #eff6ff;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
        }}
        .meeting-title {{
            font-size: 20px;
            font-weight: 600;
            color: #1f2937;
            margin-bottom: 8px;
        }}
        .meeting-date {{
            color: #6b7280;
            font-size: 14px;
            margin-bottom: 24px;
        }}
        .cta-button {{
            display: inline-block;
            padding: 14px 32px;
            background-color: #4f46e5;
            color: #ffffff;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            font-size: 16px;
            transition: background-color 0.2s;
        }}
        .cta-button:hover {{
            background-color: #4338ca;
        }}
        .insights-section {{
            padding: 40px;
            text-align: center;
            background-color: #fafafa;
        }}
        .insights-title {{
            font-size: 20px;
            color: #6b7280;
            margin-bottom: 10px;
        }}
        .features {{
            display: table;
            width: 100%;
            margin-top: 30px;
        }}
        .feature-row {{
            display: table-row;
        }}
        .feature {{
            display: table-cell;
            padding: 20px;
            width: 50%;
            vertical-align: top;
        }}
        .feature-icon {{
            width: 48px;
            height: 48px;
            margin: 0 auto 12px;
            background-color: #f3f4f6;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
        }}
        .feature-title {{
            font-weight: 600;
            color: #1f2937;
            margin-bottom: 8px;
            font-size: 16px;
        }}
        .feature-desc {{
            color: #6b7280;
            font-size: 14px;
            line-height: 1.5;
        }}
        .footer {{
            padding: 40px;
            text-align: center;
            background-color: #1f2937;
            color: #9ca3af;
            font-size: 12px;
        }}
        .footer a {{
            color: #60a5fa;
            text-decoration: none;
        }}
        @media only screen and (max-width: 600px) {{
            .features {{
                display: block;
            }}
            .feature {{
                display: block;
                width: 100%;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div class="logo">🤖 AI Meeting Assistant</div>
        </div>

        <!-- Invited By Section -->
        <div class="invited-by">
            <div class="invited-icon">🎤</div>
            <div class="invited-name">{recipient_name}</div>
            <div class="invited-email">({recipient_email})</div>
            <div class="invitation-text">{invited_text} AI Notetaker to your meeting</div>
            <div class="subtitle">To record and take notes</div>
        </div>

        <!-- Meeting Card -->
        <div class="meeting-card">
            <div class="meeting-icon">📅</div>
            <div class="meeting-title">{meeting_title}</div>
            <div class="meeting-date">{formatted_date}</div>
            <a href="{meeting_url}" class="cta-button">View meeting recap</a>
        </div>

        <!-- Insights Section -->
        <div class="insights-section">
            <div class="insights-title">🔍 In this meeting</div>
            <a href="{meeting_url}" style="color: #4f46e5; text-decoration: none; font-weight: 600;">See more insights</a>
        </div>

        <!-- Features -->
        <div style="padding: 40px; background-color: #ffffff;">
            <h2 style="text-align: center; color: #1f2937; margin-bottom: 40px;">
                Supercharge your meetings with AI Assistant
            </h2>
            
            <div class="features">
                <div class="feature-row">
                    <div class="feature">
                        <div class="feature-icon">🎙️</div>
                        <div class="feature-title">Record</div>
                        <div class="feature-desc">
                            Just invite AI Notetaker to your meetings for seamless recording.
                        </div>
                    </div>
                    <div class="feature">
                        <div class="feature-icon">📝</div>
                        <div class="feature-title">Transcribe</div>
                        <div class="feature-desc">
                            Easily transcribe your live meetings with advanced AI models.
                        </div>
                    </div>
                </div>
                <div class="feature-row">
                    <div class="feature">
                        <div class="feature-icon">📋</div>
                        <div class="feature-title">Summarize</div>
                        <div class="feature-desc">
                            Instantly get meeting overview, key points, action items and more.
                        </div>
                    </div>
                    <div class="feature">
                        <div class="feature-icon">📊</div>
                        <div class="feature-title">Analyze</div>
                        <div class="feature-desc">
                            Understand your meetings better with conversation intelligence.
                        </div>
                    </div>
                </div>
                <div class="feature-row">
                    <div class="feature">
                        <div class="feature-icon">🔍</div>
                        <div class="feature-title">Smart Search</div>
                        <div class="feature-desc">
                            Search across meetings, transcripts, action items and highlights.
                        </div>
                    </div>
                    <div class="feature">
                        <div class="feature-icon">👥</div>
                        <div class="feature-title">Collaborate</div>
                        <div class="feature-desc">
                            Comment or mark specific parts to collaborate with teammates.
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Footer -->
        <div class="footer">
            <p style="margin: 0 0 10px 0;">Meeting notes taken on behalf of {recipient_email}</p>
            <p style="margin: 0 0 20px 0;">
                <a href="{frontend_url}/settings/notifications">Unsubscribe from email notifications</a>
            </p>
            <p style="margin: 0; font-size: 11px;">
                AI Meeting Assistant • Powered by Advanced AI<br>
                <a href="{frontend_url}/privacy">Privacy Policy</a> • 
                <a href="{frontend_url}/terms">Terms of Service</a>
            </p>
        </div>
    </div>
</body>
</html>
"""

        # Plain text fallback
        text_body = f"""
AI Meeting Assistant
Your meeting recap - {meeting_title}

{recipient_name} ({recipient_email})
{invited_text} AI Notetaker to your meeting
To record and take notes

{meeting_title}
{formatted_date}

View meeting recap: {meeting_url}

---
Supercharge your meetings with AI Assistant

Record - Just invite AI Notetaker to your meetings for seamless recording.
Transcribe - Easily transcribe your live meetings with advanced AI models.
Summarize - Instantly get meeting overview, key points, action items and more.
Analyze - Understand your meetings better with conversation intelligence.
Smart Search - Search across meetings, transcripts, action items and highlights.
Collaborate - Comment or mark specific parts to collaborate with teammates.

---
Meeting notes taken on behalf of {recipient_email}
Unsubscribe: {frontend_url}/settings/notifications

AI Meeting Assistant • Powered by Advanced AI
"""

        return {
            'subject': f'Your meeting recap - {meeting_title}',
            'html': html_body,
            'text': text_body
        }

    @staticmethod
    def send_email(
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str
    ) -> bool:
        """
        Send an email using SMTP.
        
        Args:
            to_email: Recipient email address
            subject: Email subject line
            html_body: HTML version of email
            text_body: Plain text version of email
            
        Returns:
            True if sent successfully, False otherwise
        """
        # Check if email is configured
        if not settings.SMTP_HOST or not settings.SMTP_PORT:
            logger.warning("Email not configured. Skipping email send.")
            return False

        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
            msg['To'] = to_email

            # Attach both plain text and HTML versions
            part1 = MIMEText(text_body, 'plain')
            part2 = MIMEText(html_body, 'html')
            msg.attach(part1)
            msg.attach(part2)

            # Send email
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                # Use TLS if configured
                if settings.SMTP_TLS:
                    server.starttls()
                
                # Login if credentials provided
                if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                    server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                
                server.send_message(msg)
            
            logger.info(f"Meeting recap email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False

    @staticmethod
    def send_meeting_recap(
        recipient_email: str,
        recipient_name: str,
        meeting_title: str,
        meeting_date: datetime,
        meeting_id: int,
        invited_by: Optional[str] = None
    ) -> bool:
        """
        Send a meeting recap email (convenience method).
        
        Args:
            recipient_email: Email address to send to
            recipient_name: Name of the recipient
            meeting_title: Title of the meeting
            meeting_date: When the meeting took place
            meeting_id: Database ID for the meeting
            invited_by: Email of person who invited the bot
            
        Returns:
            True if sent successfully, False otherwise
        """
        email_content = EmailService.create_meeting_recap_email(
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            meeting_id=meeting_id,
            invited_by=invited_by
        )
        
        return EmailService.send_email(
            to_email=recipient_email,
            subject=email_content['subject'],
            html_body=email_content['html'],
            text_body=email_content['text']
        )
