"""
Microsoft Graph API Integration
Creates Outlook/Microsoft 365 contacts directly without manual VCF import.

Authentication: Uses MSAL device code flow (ideal for desktop/CLI apps).
User visits https://microsoft.com/devicelogin and enters a code.

Required Azure AD App Registration:
- Redirect URI: http://localhost (for device code flow)
- API Permissions: Contacts.ReadWrite, User.Read
- Supported account types: Personal + Organizational

Install: pip install msal requests
"""

import json
import os
import time
import logging
from typing import Optional, Dict, List
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class MSGraphContactManager:
    """
    Microsoft Graph API client for managing Outlook contacts.

    Usage:
        manager = MSGraphContactManager(client_id="your-app-id")
        manager.authenticate()  # User completes device code flow
        manager.create_contact(contact_data)
    """

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
    AUTHORITY = "https://login.microsoftonline.com/common"
    SCOPES = ["Contacts.ReadWrite", "User.Read"]

    # Token cache file location
    TOKEN_CACHE_FILE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "temp",
        ".ms_graph_token_cache.json"
    )

    def __init__(
        self,
        client_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        token_cache_path: Optional[str] = None,
    ):
        """
        Initialize MS Graph client.

        Args:
            client_id: Azure AD application (client) ID
            tenant_id: Azure AD tenant ID (use 'common' for multi-tenant)
            token_cache_path: Custom path for token cache file
        """
        self.client_id = client_id or os.environ.get("MS_GRAPH_CLIENT_ID")
        self.tenant_id = tenant_id or os.environ.get("MS_GRAPH_TENANT_ID", "common")
        self.token_cache_path = token_cache_path or self.TOKEN_CACHE_FILE

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._msal_app = None
        self._account = None

    @property
    def is_configured(self) -> bool:
        """Check if client_id is configured."""
        return bool(self.client_id)

    @property
    def is_authenticated(self) -> bool:
        """Check if we have a valid (non-expired) access token."""
        return bool(self._access_token and time.time() < self._token_expires_at)

    def _get_msal_app(self):
        """Create or return MSAL public client application."""
        if self._msal_app is None:
            try:
                import msal
            except ImportError:
                raise ImportError(
                    "MSAL library required. Install with: pip install msal"
                )

            if not self.client_id:
                raise ValueError(
                    "MS Graph client_id not configured. "
                    "Set MS_GRAPH_CLIENT_ID environment variable or pass client_id."
                )

            authority = f"https://login.microsoftonline.com/{self.tenant_id}"

            # Load token cache if exists
            cache = msal.SerializableTokenCache()
            if os.path.exists(self.token_cache_path):
                try:
                    with open(self.token_cache_path, 'r') as f:
                        cache.deserialize(f.read())
                except Exception as e:
                    logger.warning(f"Failed to load token cache: {e}")

            self._msal_app = msal.PublicClientApplication(
                self.client_id,
                authority=authority,
                token_cache=cache,
            )

        return self._msal_app

    def _save_token_cache(self):
        """Persist token cache to disk with owner-only permissions."""
        app = self._get_msal_app()
        if app.token_cache.has_state_changed:
            cache_dir = os.path.dirname(self.token_cache_path)
            os.makedirs(cache_dir, exist_ok=True)
            # Open with 0600 from the start so the token is never world-readable
            fd = os.open(
                self.token_cache_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(fd, 'w') as f:
                f.write(app.token_cache.serialize())
            # Re-apply in case the file pre-existed with looser perms
            try:
                os.chmod(self.token_cache_path, 0o600)
            except OSError:
                pass

    def _acquire_token_silent(self) -> Optional[str]:
        """Try to acquire token silently from cache."""
        app = self._get_msal_app()
        accounts = app.get_accounts()

        if accounts:
            self._account = accounts[0]
            result = app.acquire_token_silent(
                self.SCOPES,
                account=self._account,
            )

            if result and "access_token" in result:
                self._access_token = result["access_token"]
                self._token_expires_at = time.time() + result.get("expires_in", 3600)
                self._save_token_cache()
                return self._access_token

        return None

    def authenticate(self, callback=None) -> Dict:
        """
        Authenticate using device code flow.

        Args:
            callback: Optional function(user_code, verification_uri, message)
                     called when user action is needed.

        Returns:
            Dict with 'success', 'user_code', 'message' keys
        """
        # Try silent authentication first
        token = self._acquire_token_silent()
        if token:
            return {
                "success": True,
                "message": "Authenticated from cached token",
                "user_code": None,
            }

        # Need interactive authentication
        app = self._get_msal_app()
        flow = app.initiate_device_flow(scopes=self.SCOPES)

        if "user_code" not in flow:
            error_msg = flow.get("error_description", "Failed to initiate device flow")
            return {
                "success": False,
                "message": error_msg,
                "user_code": None,
            }

        user_code = flow["user_code"]
        verification_uri = flow.get("verification_uri", "https://microsoft.com/devicelogin")
        message = flow.get("message", f"Visit {verification_uri} and enter code: {user_code}")

        if callback:
            callback(user_code, verification_uri, message)

        # Wait for user to complete authentication
        result = app.acquire_token_by_device_flow(flow)

        if "access_token" in result:
            self._access_token = result["access_token"]
            self._token_expires_at = time.time() + result.get("expires_in", 3600)
            self._account = result.get("id_token_claims", {})
            self._save_token_cache()

            return {
                "success": True,
                "message": f"Authenticated as {result.get('id_token_claims', {}).get('preferred_username', 'user')}",
                "user_code": user_code,
            }
        else:
            return {
                "success": False,
                "message": result.get("error_description", "Authentication failed"),
                "user_code": user_code,
            }

    def _ensure_authenticated(self):
        """Ensure we have a valid token, refreshing if needed."""
        if not self.is_authenticated:
            token = self._acquire_token_silent()
            if not token:
                raise RuntimeError(
                    "Not authenticated. Call authenticate() first."
                )

    def _make_request(self, method: str, endpoint: str, json_data=None) -> requests.Response:
        """Make authenticated request to Graph API."""
        self._ensure_authenticated()

        url = f"{self.GRAPH_BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
            timeout=30,
        )

        return response

    def get_me(self) -> Optional[Dict]:
        """Get current user profile to verify authentication."""
        try:
            response = self._make_request("GET", "/me")
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None

    def contact_to_graph_format(self, contact_data: Dict) -> Dict:
        """
        Convert contact data dictionary to Microsoft Graph contact format.

        Args:
            contact_data: Contact dictionary (legacy format with camelCase keys)

        Returns:
            Dict in Microsoft Graph API contact format
        """
        graph_contact = {}

        # Name
        if contact_data.get('firstName'):
            graph_contact['givenName'] = contact_data['firstName']
        if contact_data.get('lastName'):
            graph_contact['surname'] = contact_data['lastName']

        # If only fullName, try to split
        if not graph_contact.get('givenName') and not graph_contact.get('surname'):
            full_name = contact_data.get('fullName', '')
            if full_name:
                parts = full_name.strip().split(' ', 1)
                graph_contact['givenName'] = parts[0]
                if len(parts) > 1:
                    graph_contact['surname'] = parts[1]

        # Display name
        display_name = contact_data.get('fullName') or \
            f"{contact_data.get('firstName', '')} {contact_data.get('lastName', '')}".strip()
        if display_name:
            graph_contact['displayName'] = display_name

        # Job title
        if contact_data.get('title'):
            graph_contact['jobTitle'] = contact_data['title']

        # Company
        if contact_data.get('company'):
            graph_contact['companyName'] = contact_data['company']

        # Email
        if contact_data.get('email'):
            graph_contact['emailAddresses'] = [
                {
                    "address": contact_data['email'],
                    "name": display_name or contact_data['email'],
                }
            ]

        # Phone numbers
        phones = []
        if contact_data.get('phone'):
            phones.append(contact_data['phone'])
        graph_contact['businessPhones'] = phones

        if contact_data.get('mobile'):
            graph_contact['mobilePhone'] = contact_data['mobile']

        # Address
        business_address = {}
        if contact_data.get('address'):
            business_address['street'] = contact_data['address']
        if contact_data.get('city'):
            business_address['city'] = contact_data['city']
        if contact_data.get('state'):
            business_address['state'] = contact_data['state']
        if contact_data.get('zip'):
            business_address['postalCode'] = contact_data['zip']
        if contact_data.get('country'):
            business_address['countryOrRegion'] = contact_data['country']

        if business_address:
            graph_contact['businessAddress'] = business_address

        # Website
        urls = []
        if contact_data.get('website'):
            urls.append(contact_data['website'])
        if contact_data.get('linkedin'):
            urls.append(contact_data['linkedin'])

        # Notes
        notes_parts = []
        if contact_data.get('notes'):
            notes_parts.append(contact_data['notes'])
        if contact_data.get('linkedin'):
            notes_parts.append(f"LinkedIn: {contact_data['linkedin']}")
        if urls:
            # MS Graph doesn't have a direct URL field for contacts, put in personalNotes
            notes_parts.append(f"Website: {contact_data.get('website', '')}")

        if notes_parts:
            graph_contact['personalNotes'] = "\n".join(notes_parts)

        return graph_contact

    def create_contact(self, contact_data: Dict) -> Dict:
        """
        Create a single contact in Outlook.

        Args:
            contact_data: Contact dictionary (legacy format)

        Returns:
            Dict with 'success', 'contact_id', 'display_name', 'error'
        """
        try:
            graph_contact = self.contact_to_graph_format(contact_data)

            response = self._make_request("POST", "/me/contacts", graph_contact)

            if response.status_code == 201:
                created = response.json()
                return {
                    "success": True,
                    "contact_id": created.get("id"),
                    "display_name": created.get("displayName"),
                    "error": None,
                }
            else:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text[:200])
                return {
                    "success": False,
                    "contact_id": None,
                    "display_name": None,
                    "error": f"API error {response.status_code}: {error_msg}",
                }

        except Exception as e:
            return {
                "success": False,
                "contact_id": None,
                "display_name": None,
                "error": str(e),
            }

    def batch_create_contacts(
        self,
        contacts: List[Dict],
        progress_callback=None,
        skip_duplicates: bool = True,
    ) -> Dict:
        """
        Create multiple contacts in Outlook.

        Args:
            contacts: List of contact dictionaries
            progress_callback: Optional function(current, total, result)
            skip_duplicates: Check for existing contacts by email before creating

        Returns:
            Dict with 'created', 'skipped', 'failed', 'results'
        """
        existing_emails = set()
        if skip_duplicates:
            try:
                existing_emails = self._get_existing_emails()
            except Exception as e:
                logger.warning(f"Could not check existing contacts: {e}")

        results = []
        created = 0
        skipped = 0
        failed = 0

        for i, contact in enumerate(contacts):
            # Check for duplicate
            email = contact.get('email', '').lower()
            if skip_duplicates and email and email in existing_emails:
                results.append({
                    "success": False,
                    "display_name": contact.get('fullName', ''),
                    "error": "Duplicate (email already exists)",
                    "skipped": True,
                })
                skipped += 1
            else:
                result = self.create_contact(contact)
                results.append(result)

                if result["success"]:
                    created += 1
                    if email:
                        existing_emails.add(email)
                else:
                    failed += 1

            if progress_callback:
                progress_callback(i + 1, len(contacts), results[-1])

        return {
            "created": created,
            "skipped": skipped,
            "failed": failed,
            "total": len(contacts),
            "results": results,
        }

    def _get_existing_emails(self) -> set:
        """Get set of existing contact emails for duplicate detection."""
        emails = set()

        # Request only email fields for efficiency
        response = self._make_request(
            "GET",
            "/me/contacts?$select=emailAddresses&$top=1000"
        )

        if response.status_code == 200:
            contacts = response.json().get("value", [])
            for contact in contacts:
                for email_entry in contact.get("emailAddresses", []):
                    addr = email_entry.get("address", "").lower()
                    if addr:
                        emails.add(addr)

        return emails

    def search_contacts(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search existing contacts.

        Args:
            query: Search string (searches name and email)
            max_results: Maximum results to return

        Returns:
            List of contact dictionaries
        """
        try:
            response = self._make_request(
                "GET",
                f"/me/contacts?$search=\"{query}\"&$top={max_results}"
                "&$select=displayName,emailAddresses,businessPhones,companyName,jobTitle"
            )

            if response.status_code == 200:
                return response.json().get("value", [])
            return []
        except Exception:
            return []

    def logout(self):
        """Clear authentication state and cached tokens."""
        self._access_token = None
        self._token_expires_at = 0
        self._account = None
        self._msal_app = None

        if os.path.exists(self.token_cache_path):
            try:
                os.remove(self.token_cache_path)
            except Exception:
                pass
