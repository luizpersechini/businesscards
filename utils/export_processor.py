"""
Export Processor Module
Handles exporting contacts to multiple formats: CSV, Excel (XLSX), and Outlook (VCF).
"""

import pandas as pd
from typing import List, Dict
from io import BytesIO
import zipfile
from datetime import datetime


# CSV/XLSX formula-injection mitigation (security audit 2026-05-20).
# OCR'd business-card fields can contain things like  =cmd|'/c calc'!A1  or
# @SUM(...) which spreadsheet apps execute on open. Prefix any value that
# starts with a formula trigger with a single quote so it's treated as text.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _neutralize_formula(value):
    """Return value unchanged unless it's a string starting with a spreadsheet
    formula trigger, in which case prefix it with an apostrophe."""
    if isinstance(value, str) and value and value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


class ExportProcessor:
    """Export contacts to various formats."""

    def __init__(self):
        """Initialize the export processor."""
        pass

    def contacts_to_dataframe(self, contacts: List[Dict]) -> pd.DataFrame:
        """
        Convert list of contacts to pandas DataFrame.

        Args:
            contacts: List of contact dictionaries

        Returns:
            pandas DataFrame with contact data
        """
        # Define standard columns
        columns = [
            "firstName",
            "lastName",
            "fullName",
            "title",
            "company",
            "email",
            "phone",
            "mobile",
            "address",
            "city",
            "state",
            "zip",
            "country",
            "website",
            "linkedin",
            "notes",
        ]

        # Create list of rows (formula-injection neutralized — protects both
        # the CSV and Excel exporters that flow through this method)
        rows = []
        for contact in contacts:
            row = {}
            for col in columns:
                row[col] = _neutralize_formula(contact.get(col, ""))
            rows.append(row)

        # Create DataFrame
        df = pd.DataFrame(rows, columns=columns)

        # Rename columns to be more user-friendly
        df.columns = [
            "First Name",
            "Last Name",
            "Full Name",
            "Title",
            "Company",
            "Email",
            "Phone",
            "Mobile",
            "Address",
            "City",
            "State",
            "ZIP",
            "Country",
            "Website",
            "LinkedIn",
            "Notes",
        ]

        return df

    def export_single_to_csv(self, contact: Dict, include_source: bool = False) -> bytes:
        """
        Export a single contact to CSV format.

        Args:
            contact: Single contact dictionary
            include_source: Whether to include source file column

        Returns:
            CSV data as bytes
        """
        # Wrap single contact in a list
        return self.export_to_csv([contact], include_source=include_source)

    def export_to_csv(self, contacts: List[Dict], include_source: bool = True) -> bytes:
        """
        Export contacts to CSV format.

        Args:
            contacts: List of contact dictionaries
            include_source: Whether to include source file column

        Returns:
            CSV data as bytes
        """
        df = self.contacts_to_dataframe(contacts)

        # Add source column if requested
        if include_source:
            sources = [c.get("source", "Unknown") for c in contacts]
            df.insert(0, "Source", sources)

        # Convert to CSV with explicit comma delimiter and Windows line endings
        buffer = BytesIO()
        df.to_csv(
            buffer,
            index=False,
            encoding="utf-8-sig",  # UTF-8 with BOM for Excel compatibility
            sep=",",
            lineterminator="\r\n",  # Windows-style CRLF for better compatibility
            quoting=1,  # QUOTE_MINIMAL
        )
        return buffer.getvalue()

    def export_to_excel(self, contacts: List[Dict], include_source: bool = True) -> bytes:
        """
        Export contacts to Excel (XLSX) format.

        Args:
            contacts: List of contact dictionaries
            include_source: Whether to include source file column

        Returns:
            Excel data as bytes
        """
        df = self.contacts_to_dataframe(contacts)

        # Add source column if requested
        if include_source:
            sources = [c.get("source", "Unknown") for c in contacts]
            df.insert(0, "Source", sources)

        # Convert to Excel with formatting
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Contacts")

            # Get workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets["Contacts"]

            # Auto-adjust column widths
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter

                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass

                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width

            # Make header row bold
            from openpyxl.styles import Font

            bold_font = Font(bold=True)
            for cell in worksheet[1]:
                cell.font = bold_font

        return buffer.getvalue()

    def export_to_outlook_csv(
        self,
        contacts: List[Dict],
        email_field_name: str = "E-mail Address",
        phone_field_name: str = "Business Phone",
    ) -> bytes:
        """
        Export contacts to Outlook-compatible CSV format.
        Uses exact Outlook column names and Windows-style line endings (CRLF).
        Focuses on essential fields in correct order for auto-mapping.

        Args:
            contacts: List of contact dictionaries
            email_field_name: Field name for email (options: 'E-mail Address', 'Email Address', 'Email')
            phone_field_name: Field name for phone (options: 'Business Phone', 'Phone', 'Work Phone')

        Returns:
            Outlook CSV data as bytes
        """
        # Outlook CSV requires EXACT column names and order as Outlook exports
        # Based on actual Outlook export format analysis
        # CRITICAL: Order matters - Outlook expects fields in specific positions
        outlook_columns = [
            # Position 1-3: Name fields (ALWAYS first - Outlook requirement)
            ("First Name", "firstName"),
            ("Middle Name", None),
            ("Last Name", "lastName"),
            # Position 4-8: Additional name fields
            ("Title", None),  # Honorific (Mr., Mrs., etc.)
            ("Suffix", None),
            ("Nickname", None),
            ("Given Yomi", None),
            ("Surname Yomi", None),
            # Position 9: Email (EXACT position as Outlook exports)
            (email_field_name, "email"),
            ("E-mail 2 Address", None),
            ("E-mail 3 Address", None),
            # Position 12-14: Phone numbers (EXACT positions)
            ("Home Phone", None),
            ("Home Phone 2", None),
            (phone_field_name, "phone"),
            ("Business Phone 2", None),
            ("Mobile Phone", "mobile"),
            # Position 17-29: Additional phone fields
            ("Car Phone", None),
            ("Other Phone", None),
            ("Primary Phone", None),
            ("Pager", None),
            ("Business Fax", None),
            ("Home Fax", None),
            ("Other Fax", None),
            ("Company Main Phone", None),
            ("Callback", None),
            ("Radio Phone", None),
            ("Telex", None),
            ("TTY/TDD Phone", None),
            ("IMAddress", None),
            # Position 30: Job Title
            ("Job Title", "title"),
            ("Department", None),
            # Position 32: Company (EXACT position as Outlook exports)
            ("Company", "company"),
            # Position 33-37: Additional company fields
            ("Office Location", None),
            ("Manager's Name", None),
            ("Assistant's Name", None),
            ("Assistant's Phone", None),
            ("Company Yomi", None),
            # Position 38-42: Business address (EXACT positions)
            ("Business Street", "address"),
            ("Business City", "city"),
            ("Business State", "state"),
            ("Business Postal Code", "zip"),
            ("Business Country/Region", "country"),
            # Position 43-48: Home address
            ("Home Street", None),
            ("Home City", None),
            ("Home State", None),
            ("Home Postal Code", None),
            ("Home Country/Region", None),
            # Position 49-53: Other address
            ("Other Street", None),
            ("Other City", None),
            ("Other State", None),
            ("Other Postal Code", None),
            ("Other Country/Region", None),
            # Position 54-58: Web and social
            ("Personal Web Page", None),
            ("Spouse", None),
            ("Schools", None),
            ("Hobby", None),
            ("Location", None),
            ("Web Page", "website"),
            # Position 59-61: Dates and notes
            ("Birthday", None),
            ("Anniversary", None),
            ("Notes", "notes"),
        ]

        # Create rows with Outlook-specific columns (maintaining order)
        rows = []
        for contact in contacts:
            # Pre-process contact data: split fullName if firstName/lastName are missing
            processed_contact = contact.copy()

            # If firstName or lastName is missing, try to split fullName
            if not processed_contact.get("firstName") and not processed_contact.get("lastName"):
                full_name = processed_contact.get("fullName", "")
                if full_name:
                    name_parts = full_name.strip().split(" ", 1)
                    if len(name_parts) == 1:
                        # Only one name, use as firstName
                        processed_contact["firstName"] = name_parts[0]
                        processed_contact["lastName"] = ""
                    elif len(name_parts) == 2:
                        # Split into first and last
                        processed_contact["firstName"] = name_parts[0]
                        processed_contact["lastName"] = name_parts[1]

            row = {}
            for outlook_col, contact_key in outlook_columns:
                if contact_key is None:
                    # Field not supported, leave empty
                    row[outlook_col] = ""
                else:
                    # Get value from processed contact data
                    value = processed_contact.get(contact_key, "")
                    # Ensure value is string and strip whitespace
                    # Also ensure None/null values become empty strings
                    if value is None or value == "null" or value == "None":
                        value = ""
                    else:
                        value = str(value).strip()
                        # Remove any non-printable characters that might confuse Outlook
                        value = "".join(
                            char
                            for char in value
                            if char.isprintable() or char in ["\n", "\r", "\t"]
                        )

                        # Special handling for email: CRITICAL - remove commas and quotes
                        if "email" in outlook_col.lower() or "e-mail" in outlook_col.lower():
                            # CRITICAL: Remove commas from email (commas break CSV parsing)
                            value = value.replace(",", "")
                            # Remove quotes from email
                            value = value.replace('"', "").replace("'", "")
                            # Remove all whitespace
                            value = (
                                value.replace(" ", "")
                                .replace("\t", "")
                                .replace("\n", "")
                                .replace("\r", "")
                            )
                            # Convert to lowercase
                            value = value.lower()
                            # Validate email format
                            if "@" in value and "." in value.split("@")[1]:
                                # Valid email format
                                pass
                            else:
                                # Invalid email, clear it
                                value = ""

                        # Special handling for phone: remove commas and quotes
                        elif "Phone" in outlook_col or "phone" in outlook_col.lower():
                            # CRITICAL: Remove commas from phone numbers
                            value = value.replace(",", " ")
                            # Remove quotes
                            value = value.replace('"', "").replace("'", "")
                            # Keep only +, digits, spaces, parentheses, hyphens
                            value = "".join(
                                char
                                for char in value
                                if char.isdigit() or char in ["+", " ", "(", ")", "-"]
                            )
                            # Remove extra spaces
                            value = " ".join(value.split())

                        # For all other fields: remove commas that could break CSV
                        else:
                            # Remove problematic characters that could break CSV parsing
                            # But preserve commas in addresses (they're part of the data)
                            if outlook_col not in ["Business Street", "Address", "Notes"]:
                                # Remove commas from non-address fields
                                value = value.replace(",", ";")
                            # Remove quotes
                            value = value.replace('"', "").replace("'", "")

                    row[outlook_col] = _neutralize_formula(value) if value else ""
            rows.append(row)

        # Create DataFrame with exact Outlook column order (preserve order from list)
        column_order = [col[0] for col in outlook_columns]
        df = pd.DataFrame(rows, columns=column_order)

        # Convert to CSV with Windows-style line endings (CRLF) and UTF-8-BOM encoding
        # Use QUOTE_ALL to ensure all fields are properly quoted (more robust for Outlook)
        buffer = BytesIO()
        df.to_csv(
            buffer,
            index=False,
            encoding="utf-8-sig",  # UTF-8 with BOM (required for Excel/Outlook)
            lineterminator="\r\n",  # Windows-style CRLF (required for Outlook)
            quoting=1,  # QUOTE_ALL - quote all fields for maximum compatibility
            doublequote=True,  # Escape quotes by doubling them
            escapechar=None,  # No escape char needed when doublequote is True
        )
        return buffer.getvalue()

    def export_to_outlook_csv_simple(
        self,
        contacts: List[Dict],
        email_field_name: str = "Email Address",
        phone_field_name: str = "Phone",
        use_quotes: bool = False,
    ) -> bytes:
        """
        Export contacts to simplified Outlook-compatible CSV format.
        Minimal fields only for maximum compatibility.

        Args:
            contacts: List of contact dictionaries
            email_field_name: Field name for email (options: 'E-mail Address', 'Email Address', 'Email')
            phone_field_name: Field name for phone (options: 'Business Phone', 'Phone', 'Work Phone')
            use_quotes: Whether to quote fields (False = QUOTE_NONE, True = QUOTE_ALL)

        Returns:
            Outlook CSV data as bytes
        """
        # Minimal field set - only essential fields
        outlook_columns = [
            ("First Name", "firstName"),
            ("Last Name", "lastName"),
            ("Company", "company"),
            (email_field_name, "email"),
            (phone_field_name, "phone"),
        ]

        # Create rows
        rows = []
        for contact in contacts:
            processed_contact = contact.copy()

            # Split fullName if needed
            if not processed_contact.get("firstName") and not processed_contact.get("lastName"):
                full_name = processed_contact.get("fullName", "")
                if full_name:
                    name_parts = full_name.strip().split(" ", 1)
                    if len(name_parts) == 1:
                        processed_contact["firstName"] = name_parts[0]
                        processed_contact["lastName"] = ""
                    elif len(name_parts) == 2:
                        processed_contact["firstName"] = name_parts[0]
                        processed_contact["lastName"] = name_parts[1]

            row = {}
            for outlook_col, contact_key in outlook_columns:
                value = processed_contact.get(contact_key, "")

                if value is None or value == "null" or value == "None":
                    value = ""
                else:
                    value = str(value).strip()

                    # Sanitize email
                    if "email" in outlook_col.lower() or "e-mail" in outlook_col.lower():
                        value = value.replace(",", "").replace('"', "").replace("'", "")
                        value = value.replace(" ", "").lower()
                        if "@" not in value or "." not in value.split("@")[1]:
                            value = ""

                    # Sanitize phone
                    elif "phone" in outlook_col.lower():
                        value = value.replace(",", " ").replace('"', "").replace("'", "")
                        value = "".join(
                            char
                            for char in value
                            if char.isdigit() or char in ["+", " ", "(", ")", "-"]
                        )
                        value = " ".join(value.split())

                    # Sanitize other fields
                    else:
                        value = value.replace('"', "").replace("'", "")
                        # Remove commas from non-address fields
                        if outlook_col not in ["Business Street", "Address"]:
                            value = value.replace(",", ";")

                row[outlook_col] = _neutralize_formula(value) if value else ""
            rows.append(row)

        # Create DataFrame
        column_order = [col[0] for col in outlook_columns]
        df = pd.DataFrame(rows, columns=column_order)

        # Convert to CSV
        buffer = BytesIO()
        quoting_mode = 1 if use_quotes else 3  # QUOTE_ALL (1) or QUOTE_NONE (3)

        df.to_csv(
            buffer,
            index=False,
            encoding="utf-8-sig",
            lineterminator="\r\n",
            quoting=quoting_mode,
            doublequote=True if use_quotes else False,
            escapechar=None,
        )
        return buffer.getvalue()

    def create_export_package(
        self,
        contacts: List[Dict],
        vcf_files: List[tuple],
        include_csv: bool = True,
        include_excel: bool = True,
        include_outlook_csv: bool = True,
    ) -> bytes:
        """
        Create a ZIP package with multiple export formats.

        Args:
            contacts: List of contact dictionaries
            vcf_files: List of (filename, vcf_content) tuples
            include_csv: Include CSV export
            include_excel: Include Excel export
            include_outlook_csv: Include Outlook CSV export

        Returns:
            ZIP file as bytes
        """
        buffer = BytesIO()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # Add VCF files
            for filename, content in vcf_files:
                zip_file.writestr(f"vcf/{filename}", content)

            # Add CSV if requested
            if include_csv and contacts:
                csv_data = self.export_to_csv(contacts)
                zip_file.writestr(f"contacts_{timestamp}.csv", csv_data)

            # Add Excel if requested
            if include_excel and contacts:
                excel_data = self.export_to_excel(contacts)
                zip_file.writestr(f"contacts_{timestamp}.xlsx", excel_data)

            # Add Outlook CSV if requested
            if include_outlook_csv and contacts:
                outlook_csv_data = self.export_to_outlook_csv(contacts)
                zip_file.writestr(f"outlook_import_{timestamp}.csv", outlook_csv_data)

        return buffer.getvalue()

    def get_export_stats(self, contacts: List[Dict]) -> Dict:
        """
        Get statistics about the contacts for export summary.

        Args:
            contacts: List of contact dictionaries

        Returns:
            Dictionary with statistics
        """
        if not contacts:
            return {"total": 0}

        stats = {
            "total": len(contacts),
            "with_email": sum(1 for c in contacts if c.get("email")),
            "with_phone": sum(1 for c in contacts if c.get("phone") or c.get("mobile")),
            "with_company": sum(1 for c in contacts if c.get("company")),
            "with_address": sum(1 for c in contacts if c.get("address")),
        }

        return stats
