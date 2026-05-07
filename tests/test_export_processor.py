"""
Tests for export processor (utils/export_processor.py).
"""

import pytest
import pandas as pd
from io import BytesIO
from utils.export_processor import ExportProcessor


class TestExportProcessor:
    """Test ExportProcessor class."""
    
    @pytest.fixture
    def export_processor(self):
        """Create ExportProcessor instance."""
        return ExportProcessor()
    
    @pytest.fixture
    def sample_contacts(self, sample_contact_dict):
        """Sample contacts list."""
        return [sample_contact_dict]
    
    # ─── DataFrame Tests ───
    
    def test_contacts_to_dataframe(self, export_processor, sample_contacts):
        """Test converting contacts to DataFrame."""
        df = export_processor.contacts_to_dataframe(sample_contacts)
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert 'First Name' in df.columns
        assert 'Email' in df.columns
        assert df['First Name'].iloc[0] == 'John'
        assert df['Email'].iloc[0] == 'john@techcorp.com'
    
    def test_contacts_to_dataframe_multiple(self, export_processor):
        """Test converting multiple contacts."""
        contacts = [
            {'firstName': 'John', 'lastName': 'Doe', 'email': 'john@example.com'},
            {'firstName': 'Jane', 'lastName': 'Smith', 'email': 'jane@example.com'},
        ]
        
        df = export_processor.contacts_to_dataframe(contacts)
        
        assert len(df) == 2
        assert df['First Name'].tolist() == ['John', 'Jane']
    
    def test_contacts_to_dataframe_empty(self, export_processor):
        """Test converting empty contact list."""
        df = export_processor.contacts_to_dataframe([])
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
    
    # ─── CSV Export Tests ───
    
    def test_export_to_csv(self, export_processor, sample_contacts):
        """Test CSV export."""
        csv_data = export_processor.export_to_csv(sample_contacts)
        
        assert isinstance(csv_data, bytes)
        assert len(csv_data) > 0
        
        # Parse and verify
        df = pd.read_csv(BytesIO(csv_data))
        assert 'First Name' in df.columns
        assert df['First Name'].iloc[0] == 'John'
    
    def test_export_to_csv_outlook_format(self, export_processor, sample_contacts):
        """Test Outlook CSV export format."""
        csv_data = export_processor.export_to_outlook_csv(sample_contacts)
        
        assert isinstance(csv_data, bytes)
        assert len(csv_data) > 0
        
        # Verify it's valid CSV
        try:
            df = pd.read_csv(BytesIO(csv_data))
            assert len(df) > 0
        except Exception as e:
            pytest.fail(f"Invalid CSV generated: {e}")
    
    def test_export_single_to_csv(self, export_processor, sample_contact_dict):
        """Test exporting single contact to CSV."""
        csv_data = export_processor.export_single_to_csv(sample_contact_dict)
        
        assert isinstance(csv_data, bytes)
        df = pd.read_csv(BytesIO(csv_data))
        assert len(df) == 1
    
    # ─── Excel Export Tests ───
    
    def test_export_to_excel(self, export_processor, sample_contacts):
        """Test Excel export."""
        excel_data = export_processor.export_to_excel(sample_contacts)
        
        assert isinstance(excel_data, bytes)
        assert len(excel_data) > 0
        
        # Verify it's valid Excel
        try:
            df = pd.read_excel(BytesIO(excel_data))
            assert len(df) > 0
            assert 'First Name' in df.columns
        except Exception as e:
            pytest.fail(f"Invalid Excel generated: {e}")
    
    def test_export_to_excel_multiple_sheets(self, export_processor):
        """Test Excel export with formatting."""
        contacts = [
            {'firstName': 'John', 'email': 'john@example.com', 'company': 'Tech'},
            {'firstName': 'Jane', 'email': 'jane@example.com', 'company': 'Design'},
        ]
        
        excel_data = export_processor.export_to_excel(contacts)
        
        assert isinstance(excel_data, bytes)
        df = pd.read_excel(BytesIO(excel_data))
        assert len(df) == 2
    
    # ─── ZIP Export Tests ───
    
    def test_export_create_package(self, export_processor, sample_contacts):
        """Test creating export package."""
        # This tests the available create_export_package method
        vcf_files = [
            ('contact1.vcf', 'BEGIN:VCARD\nVERSION:3.0\nFN:John Doe\nEND:VCARD'),
            ('contact2.vcf', 'BEGIN:VCARD\nVERSION:3.0\nFN:Jane Smith\nEND:VCARD'),
        ]
        
        package = export_processor.create_export_package(
            sample_contacts,
            vcf_files,
            include_csv=True,
            include_excel=True,
            include_outlook_csv=True,
        )
        
        assert isinstance(package, bytes)
        assert len(package) > 0
        # ZIP files start with 'PK' magic bytes
        assert package[:2] == b'PK'
    
    # ─── Edge Cases ───
    
    def test_export_contacts_with_special_characters(self, export_processor):
        """Test exporting contacts with special characters."""
        contacts = [
            {
                'firstName': 'François',
                'lastName': "O'Brien",
                'email': 'francois@example.com',
                'company': 'Société Générale',
            }
        ]
        
        csv_data = export_processor.export_to_csv(contacts)
        df = pd.read_csv(BytesIO(csv_data))
        
        assert df['First Name'].iloc[0] == 'François'
        assert df['Last Name'].iloc[0] == "O'Brien"
    
    def test_export_contacts_with_missing_fields(self, export_processor):
        """Test exporting contacts with missing fields."""
        contacts = [
            {'firstName': 'John'},  # Minimal data
        ]
        
        csv_data = export_processor.export_to_csv(contacts)
        df = pd.read_csv(BytesIO(csv_data))
        
        assert df['First Name'].iloc[0] == 'John'
        # Missing fields should be empty or NaN
        assert pd.isna(df['Email'].iloc[0]) or df['Email'].iloc[0] == ''
    
    def test_export_contacts_empty_list(self, export_processor):
        """Test exporting empty contact list."""
        csv_data = export_processor.export_to_csv([])
        df = pd.read_csv(BytesIO(csv_data))
        
        # Should have headers but no data
        assert len(df) == 0
        assert len(df.columns) > 0
