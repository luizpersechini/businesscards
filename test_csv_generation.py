"""
Test CSV Generation Script
Generates test CSV files for Outlook import testing.
"""

import sys
sys.path.insert(0, '.')

from utils.export_processor import ExportProcessor
from utils.csv_validator import CSVValidator

def generate_test_csvs():
    """Generate test CSV files with different formats."""
    
    # Test contact data
    test_contacts = [
        {
            'firstName': 'Carlos',
            'lastName': 'Borel',
            'fullName': 'Carlos Borel',
            'title': 'Diretor',
            'company': 'Câmara Municipal de São Paulo',
            'email': 'cborel@cmpsp.gov.br',
            'phone': '+55 (11) 3082-9600',
            'mobile': '',
            'address': 'Rua Exemplo, 123',
            'city': 'São Paulo',
            'state': 'SP',
            'zip': '01000-000',
            'country': 'Brasil',
            'website': 'https://example.com',
            'notes': ''
        },
        {
            'firstName': 'João',
            'lastName': 'Silva',
            'fullName': 'João Silva',
            'title': 'Gerente',
            'company': 'Tech Corp Ltda',
            'email': 'joao.silva@techcorp.com.br',
            'phone': '+55 (21) 9876-5432',
            'mobile': '+55 (21) 99999-8888',
            'address': 'Av. Brasil, 1000',
            'city': 'Rio de Janeiro',
            'state': 'RJ',
            'zip': '20000-000',
            'country': 'Brasil',
            'website': '',
            'notes': 'Important contact'
        }
    ]
    
    export_processor = ExportProcessor()
    validator = CSVValidator()
    
    print("=" * 60)
    print("GENERATING TEST CSV FILES FOR OUTLOOK IMPORT")
    print("=" * 60)
    print()
    
    # Test 1: Standard export with E-mail Address
    print("Test 1: Standard format with 'E-mail Address'")
    csv1 = export_processor.export_to_outlook_csv(
        test_contacts,
        email_field_name='E-mail Address',
        phone_field_name='Business Phone'
    )
    
    with open('test_outlook_standard.csv', 'wb') as f:
        f.write(csv1)
    print("  ✓ Saved: test_outlook_standard.csv")
    
    report1 = validator.generate_diagnostic_report(csv1)
    print("\nDiagnostic Report:")
    print(report1)
    print("\n" + "=" * 60 + "\n")
    
    # Test 2: Alternative field names - Email Address
    print("Test 2: Alternative format with 'Email Address' (no hyphen)")
    csv2 = export_processor.export_to_outlook_csv(
        test_contacts,
        email_field_name='Email Address',
        phone_field_name='Phone'
    )
    
    with open('test_outlook_email_address.csv', 'wb') as f:
        f.write(csv2)
    print("  ✓ Saved: test_outlook_email_address.csv")
    
    report2 = validator.generate_diagnostic_report(csv2)
    print("\nDiagnostic Report:")
    print(report2)
    print("\n" + "=" * 60 + "\n")
    
    # Test 3: Simple format without quotes
    print("Test 3: Simplified format without quotes")
    csv3 = export_processor.export_to_outlook_csv_simple(
        test_contacts,
        email_field_name='Email Address',
        phone_field_name='Phone',
        use_quotes=False
    )
    
    with open('test_outlook_simple_no_quotes.csv', 'wb') as f:
        f.write(csv3)
    print("  ✓ Saved: test_outlook_simple_no_quotes.csv")
    
    report3 = validator.generate_diagnostic_report(csv3)
    print("\nDiagnostic Report:")
    print(report3)
    print("\n" + "=" * 60 + "\n")
    
    # Test 4: Simple format with quotes
    print("Test 4: Simplified format with quotes")
    csv4 = export_processor.export_to_outlook_csv_simple(
        test_contacts,
        email_field_name='Email Address',
        phone_field_name='Phone',
        use_quotes=True
    )
    
    with open('test_outlook_simple_with_quotes.csv', 'wb') as f:
        f.write(csv4)
    print("  ✓ Saved: test_outlook_simple_with_quotes.csv")
    
    report4 = validator.generate_diagnostic_report(csv4)
    print("\nDiagnostic Report:")
    print(report4)
    print("\n" + "=" * 60 + "\n")
    
    # Test 5: Minimal format - just Email (shortest name)
    print("Test 5: Minimal format with 'Email' (shortest field name)")
    csv5 = export_processor.export_to_outlook_csv_simple(
        test_contacts,
        email_field_name='Email',
        phone_field_name='Phone',
        use_quotes=False
    )
    
    with open('test_outlook_minimal.csv', 'wb') as f:
        f.write(csv5)
    print("  ✓ Saved: test_outlook_minimal.csv")
    
    report5 = validator.generate_diagnostic_report(csv5)
    print("\nDiagnostic Report:")
    print(report5)
    
    print("\n" + "=" * 60)
    print("ALL TEST FILES GENERATED")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Open each CSV file in Excel to verify format")
    print("2. Try importing each into Outlook")
    print("3. Compare which format works best with your Outlook version")
    print("4. Report which format successfully imports email and phone fields")

if __name__ == '__main__':
    generate_test_csvs()

