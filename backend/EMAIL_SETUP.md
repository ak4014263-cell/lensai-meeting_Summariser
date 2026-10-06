# Email Notification Setup Guide

## Overview

The AI Meeting Assistant now sends professional meeting recap emails automatically after every completed meeting, similar to Fireflies.ai. Users receive beautiful HTML emails with a direct link to view the full transcript, summary, action items, and decisions.

## Email Features

✅ **Professional HTML Design** - Beautiful, responsive email template  
✅ **Meeting Details** - Title, date, and time prominently displayed  
✅ **One-Click Access** - Direct link to view full meeting recap  
✅ **Feature Highlights** - Showcase AI capabilities (Record, Transcribe, Summarize, Analyze)  
✅ **Automatic Sending** - Emails sent automatically when meetings complete  
✅ **Fallback Support** - Plain text version for email clients without HTML support

## Email Configuration

### Option 1: Gmail SMTP (Recommended for Development)

1. **Enable 2-Factor Authentication** on your Gmail account
   - Go to: https://myaccount.google.com/security
   - Enable "2-Step Verification"

2. **Create an App Password**
   - Go to: https://myaccount.google.com/apppasswords
   - Select "Mail" and "Other (Custom name)"
   - Name it "AI Meeting Assistant"
   - Copy the generated 16-character password

3. **Update `.env` file** in the `backend` directory:

```bash
# Email Configuration
SEND_EMAIL_NOTIFICATIONS=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_TLS=true
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx  # Your 16-character app password
SMTP_FROM_EMAIL=your-email@gmail.com
SMTP_FROM_NAME=AI Meeting Assistant
FRONTEND_URL=http://localhost:3000
```

### Option 2: Custom SMTP Server

If you have your own SMTP server or use services like SendGrid, Mailgun, etc.:

```bash
# Email Configuration
SEND_EMAIL_NOTIFICATIONS=true
SMTP_HOST=smtp.yourserver.com
SMTP_PORT=587  # Or 465 for SSL, 25 for unencrypted
SMTP_TLS=true
SMTP_USERNAME=your-smtp-username
SMTP_PASSWORD=your-smtp-password
SMTP_FROM_EMAIL=noreply@yourdomain.com
SMTP_FROM_NAME=AI Meeting Assistant
FRONTEND_URL=https://yourdomain.com
```

### Option 3: Disable Email Notifications

If you don't want to send emails, simply set:

```bash
SEND_EMAIL_NOTIFICATIONS=false
```

## Email Template Preview

The email includes:

### Header
- **AI Meeting Assistant** branding
- Invitation information (who invited the bot)

### Meeting Card
- Meeting title
- Date and time
- "View meeting recap" call-to-action button

### Features Section
Six key features highlighted:
1. 🎙️ **Record** - Seamless meeting recording
2. 📝 **Transcribe** - Advanced AI transcription
3. 📋 **Summarize** - Instant overview and key points
4. 📊 **Analyze** - Conversation intelligence
5. 🔍 **Smart Search** - Search across meetings
6. 👥 **Collaborate** - Comment and mark highlights

### Footer
- Unsubscribe link
- Privacy policy and terms
- Professional branding

## Testing Email Setup

To test if your email configuration works:

1. **Start the backend server:**
   ```bash
   cd backend
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Complete a meeting:**
   - Join a meeting with the bot
   - Let the meeting complete normally
   - Check the backend logs for:
     ```
     [meeting XX] Meeting recap email sent to user@example.com
     ```

3. **Check your inbox:**
   - The email should arrive within seconds
   - Check spam folder if not in inbox
   - Gmail may initially mark it as spam until you mark it as "Not Spam"

## Troubleshooting

### Email Not Sending

**Check Configuration:**
```bash
# In backend/.env, ensure these are set:
SEND_EMAIL_NOTIFICATIONS=true
SMTP_HOST=smtp.gmail.com  # Not empty
SMTP_USERNAME=your-email@gmail.com  # Not empty
SMTP_PASSWORD=your-app-password  # Not empty
```

**Check Logs:**
Look for errors in the terminal running uvicorn:
```
WARNING:  Email notification failed: [error details]
```

**Common Issues:**

1. **"Authentication failed" error:**
   - Verify you're using an App Password, not your regular Gmail password
   - Ensure 2FA is enabled on your Google account

2. **"Email not configured" warning:**
   - SMTP_HOST is empty or missing
   - Check that .env file is in the correct location (backend/.env)

3. **"Connection refused" error:**
   - Check SMTP_HOST and SMTP_PORT are correct
   - Firewall might be blocking outgoing connections on port 587

4. **Emails go to spam:**
   - Normal for first few emails from a new sender
   - Mark as "Not Spam" to train your email provider
   - Consider setting up SPF/DKIM records if using custom domain

### Email Configuration Not Loading

1. **Restart the server** after changing .env:
   ```bash
   # Stop the server (Ctrl+C)
   # Start it again
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Check .env location:**
   - Must be at: `backend/.env`
   - Not in workspace root or frontend folder

3. **Verify environment variables loaded:**
   - Check startup logs for email configuration
   - Add debug print in config.py if needed

## Customization

### Changing Email Template

Edit: `backend/app/services/email_service.py`

The `create_meeting_recap_email()` method contains the HTML template.

**Key sections to customize:**
- `.logo` - Change branding text
- `.invited-icon` - Change emoji or add image
- `.meeting-icon` - Meeting card icon
- `.feature` blocks - Modify or add features
- `.footer` - Update footer text and links

### Changing "From" Name

In `.env`:
```bash
SMTP_FROM_NAME=Your Company Name
```

### Adding CC/BCC Recipients

Modify `backend/app/services/email_service.py`:

```python
msg['Cc'] = 'admin@company.com'  # Add this line
msg['Bcc'] = 'archive@company.com'  # Add this line
```

### Adding Attachments

In the `send_email()` method, before `server.send_message(msg)`:

```python
from email.mime.base import MIMEBase
from email import encoders

# Example: attach PDF report
with open('report.pdf', 'rb') as f:
    part = MIMEBase('application', 'pdf')
    part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment', filename='report.pdf')
    msg.attach(part)
```

## Production Deployment

For production environments:

1. **Use a dedicated email service:**
   - SendGrid (recommended)
   - Amazon SES
   - Mailgun
   - Postmark

2. **Set up proper DNS records:**
   - SPF record
   - DKIM signature
   - DMARC policy

3. **Use environment variables:**
   - Don't commit .env to version control
   - Use secrets management (AWS Secrets Manager, Azure Key Vault, etc.)

4. **Monitor email delivery:**
   - Set up logging for email failures
   - Track bounce and complaint rates
   - Implement retry logic for failed sends

5. **Update FRONTEND_URL:**
```bash
FRONTEND_URL=https://your-production-domain.com
```

## Security Best Practices

1. **Never commit credentials:**
   - Add `.env` to `.gitignore`
   - Use app passwords, not account passwords

2. **Rotate passwords regularly:**
   - Change SMTP credentials every 90 days
   - Revoke unused app passwords

3. **Use TLS:**
   - Always set `SMTP_TLS=true` for encrypted connections
   - Port 587 with STARTTLS is recommended

4. **Validate email addresses:**
   - Currently using user's email from database
   - Consider adding email verification

## Future Enhancements

Potential features to add:

- [ ] Email preferences (users can opt-in/opt-out)
- [ ] Digest emails (daily/weekly summaries)
- [ ] Email templates for different event types
- [ ] Rich attachments (PDF transcripts, calendars)
- [ ] Team notifications (CC participants)
- [ ] Email analytics (open rates, click tracking)
- [ ] Multi-language support
- [ ] Custom branding per organization

## Support

If you encounter issues:

1. Check this documentation
2. Review backend logs for error messages
3. Test SMTP connection independently
4. Verify .env configuration is correct

For Gmail-specific issues:
- https://support.google.com/accounts/answer/185833
- https://support.google.com/mail/answer/7126229

---

**Last Updated:** September 17, 2026  
**Version:** 1.0.0
