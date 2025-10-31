"""
Export Processor Module
Handles exporting contacts to multiple formats: CSV, Excel (XLSX), and Outlook (VCF).
"""

import pandas as pd
from typing import List, Dict
from io import BytesIO
import zipfile
from datetime import datetime


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
            'firstName', 'lastName', 'fullName', 'title', 'company',
            'email', 'phone', 'mobile', 'address', 'city', 'state',
            'zip', 'country', 'website', 'linkedin', 'notes'
        ]
        
        # Create list of rows
        rows = []
        for contact in contacts:
            row = {}
            for col in columns:
                row[col] = contact.get(col, '')
            rows.append(row)
        
        # Create DataFrame
        df = pd.DataFrame(rows, columns=columns)
        
        # Rename columns to be more user-friendly
        df.columns = [
            'First Name', 'Last Name', 'Full Name', 'Title', 'Company',
            'Email', 'Phone', 'Mobile', 'Address', 'City', 'State',
            'ZIP', 'Country', 'Website', 'LinkedIn', 'Notes'
        ]
        
        return df
    
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
            sources = [c.get('source', 'Unknown') for c in contacts]
            df.insert(0, 'Source', sources)
        
        # Convert to CSV
        buffer = BytesIO()
        df.to_csv(buffer, index=False, encoding='utf-8')
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
            sources = [c.get('source', 'Unknown') for c in contacts]
            df.insert(0, 'Source', sources)
        
        # Convert to Excel with formatting
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Contacts')
            
            # Get workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Contacts']
            
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
            for cell in worksheet[1]:
                cell.font = cell.font.copy(bold=True)
        
        return buffer.getvalue()
    
    def export_to_outlook_csv(self, contacts: List[Dict]) -> bytes:
        """
        Export contacts to Outlook-compatible CSV format.
        
        Args:
            contacts: List of contact dictionaries
            
        Returns:
            Outlook CSV data as bytes
        """
        # Outlook CSV requires specific column names
        outlook_columns = {
            'First Name': 'firstName',
            'Last Name': 'lastName',
            'Full Name': 'fullName',
            'Job Title': 'title',
            'Company': 'company',
            'E-mail Address': 'email',
            'Business Phone': 'phone',
            'Mobile Phone': 'mobile',
            'Business Street': 'address',
            'Business City': 'city',
            'Business State': 'state',
            'Business Postal Code': 'zip',
            'Business Country': 'country',
            'Web Page': 'website',
            'Notes': 'notes'
        }
        
        # Create rows with Outlook-specific columns
        rows = []
        for contact in contacts:
            row = {}
            for outlook_col, contact_key in outlook_columns.items():
                row[outlook_col] = contact.get(contact_key, '')
            rows.append(row)
        
        # Create DataFrame with Outlook columns
        df = pd.DataFrame(rows)
        
        # Convert to CSV
        buffer = BytesIO()
        df.to_csv(buffer, index=False, encoding='utf-8-sig')  # UTF-8 with BOM for Excel/Outlook
        return buffer.getvalue()
    
    def create_export_package(self, 
                             contacts: List[Dict],
                             vcf_files: List[tuple],
                             include_csv: bool = True,
                             include_excel: bool = True,
                             include_outlook_csv: bool = True) -> bytes:
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
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
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
            return {'total': 0}
        
        stats = {
            'total': len(contacts),
            'with_email': sum(1 for c in contacts if c.get('email')),
            'with_phone': sum(1 for c in contacts if c.get('phone') or c.get('mobile')),
            'with_company': sum(1 for c in contacts if c.get('company')),
            'with_address': sum(1 for c in contacts if c.get('address')),
        }
        
        return stats

