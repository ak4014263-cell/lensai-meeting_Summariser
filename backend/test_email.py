#!/usr/bin/env python3
"""
Test script for email notifications.
Sends a test meeting recap email without needing to complete a full meeting.

Usage:
    python test_email.py your-email@example.com
    python test_email.py your-email@example.com "Test Meeting Title"
"""

import sys
from datetime import datetime
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.email_service import EmailService
from app.config import settings


def test_email(recipient_email: str, meeting_title: str = "Test Meeting"):
    """Send a test meeting recap email."""
    
    print("=" * 60)
    print("AI Meeting Assistant - Email Test")
    print("=" * 60)
    print()
    
    # Check configuration
    print("📧 Email Configuration:")
    print(f"   SMTP Host: {settings.SMTP_HOST or '❌ Not configured'}")
    print(f"   SMTP Port: {settings.SMTP_PORT}")
    print(f"   SMTP TLS: {settings.SMTP_TLS}")
    print(f"   From Email: {settings.SMTP_FROM_EMAIL}")
    print(f"   From Name: {settings.SMTP_FROM_NAME}")
    print(f"   Notifications Enabled: {settings.SEND_EMAIL_NOTIFICATIONS}")
    print()
    
    if not settings.SMTP_HOST:
        print("❌ ERROR: SMTP_HOST is not configured in .env")
        print()
        print("To configure email:")
        print("1. Copy backend/.env.example to backend/.env (if not already done)")
        print("2. Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD")
        print("3. See EMAIL_SETUP.md for detailed instructions")
        return False
    
    if not settings.SEND_EMAIL_NOTIFICATIONS:
        print("⚠️  WARNING: SEND_EMAIL_NOTIFICATIONS is disabled")
        print("   Set SEND_EMAIL_NOTIFICATIONS=true in .env to enable")
        print()
    
    # Extract name from email
    recipient_name = recipient_email.split('@')[0].title()
    
    print(f"📨 Sending test email to: {recipient_email}")
    print(f"   Recipient name: {recipient_name}")
    print(f"   Meeting title: {meeting_title}")
    print(f"   Meeting date: {datetime.now().strftime('%b %dth at %I:%M %p')}")
    print()
    
    # Try to send email
    try:
        success = EmailService.send_meeting_recap(
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            meeting_title=meeting_title,
            meeting_date=datetime.now(),
            meeting_id=999,  # Fake meeting ID for testing
            invited_by="test@example.com"
        )
        
        if success:
            print("✅ SUCCESS! Email sent successfully")
            print()
            print("Check your inbox at:", recipient_email)
            print("(Also check spam folder if not in inbox)")
            print()
            return True
        else:
            print("❌ FAILED: Email could not be sent")
            print()
            print("Possible reasons:")
            print("- SMTP credentials are incorrect")
            print("- SMTP server is unreachable")
            print("- Email is not configured (check .env)")
            print()
            print("Check the output above for specific error messages")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        print()
        print("Common issues:")
        print()
        print("1. Authentication failed:")
        print("   - Use App Password for Gmail (not regular password)")
        print("   - Enable 2FA first: https://myaccount.google.com/security")
        print("   - Create App Password: https://myaccount.google.com/apppasswords")
        print()
        print("2. Connection refused:")
        print("   - Check SMTP_HOST and SMTP_PORT")
        print("   - Check firewall settings")
        print()
        print("3. Configuration not found:")
        print("   - Ensure .env file exists in backend/ directory")
        print("   - Check that SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD are set")
        print()
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_email.py <recipient-email> [meeting-title]")
        print()
        print("Examples:")
        print("  python test_email.py your-email@gmail.com")
        print("  python test_email.py your-email@gmail.com 'Project Kickoff Meeting'")
        sys.exit(1)
    
    recipient = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else "Test Meeting"
    
    success = test_email(recipient, title)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
