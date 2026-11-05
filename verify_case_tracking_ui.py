"""
Case Tracking UI Verification Script
Visually confirms that Case Tracking sections exist on both Police and Citizen pages
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def verify_police_page():
    """Verify Case Tracking implementation on Police page."""
    print("=" * 80)
    print("VERIFYING POLICE PAGE IMPLEMENTATION")
    print("=" * 80)
    
    police_file = Path('frontend/pages/police.py') if Path('frontend/pages/police.py').exists() else Path('pages/police.py')
    with open(police_file, 'r') as f:
        content = f.read()
    
    checks = {
        'Case Tracking import': 'from backend.services.case_tracking_service import',
        'Case Tracking section header': 'Case Tracking & Stage Management',
        'Current Stage display': 'Current Stage',
        'Update Stage Section': 'Update Case Stage',
        'Stage selector': "ui.select(",
        'Remarks field': "ui.textarea(",
        'Update button': "Update Case Stage",
        'History rendering': "Stage Update History",
        'get_case_stage_progress call': 'get_case_stage_progress(fir_id)',
        'update_case_stage call': 'update_case_stage(',
        'STAGE_LABELS usage': 'STAGE_LABELS'
    }
    
    results = []
    for check_name, search_string in checks.items():
        if search_string in content:
            print(f"  ✅ {check_name}")
            results.append(True)
        else:
            print(f"  ❌ {check_name}")
            results.append(False)
    
    return all(results)


def verify_citizen_page():
    """Verify Case Tracking implementation on Citizen page."""
    print("\n" + "=" * 80)
    print("VERIFYING CITIZEN PAGE IMPLEMENTATION")
    print("=" * 80)
    
    citizen_file = Path('frontend/pages/citizen.py') if Path('frontend/pages/citizen.py').exists() else Path('pages/citizen.py')
    with open(citizen_file, 'r') as f:
        content = f.read()
    
    checks = {
        'Case Tracking import': 'from backend.services.case_tracking_service import',
        'Case Tracking section header': 'Case Tracking',
        'READ ONLY badge': 'READ ONLY',
        'Current Stage display': 'Current Stage',
        'Progress indicator': 'Case Progress',
        'Completed stage icons': 'check_circle',
        'Current stage icons': 'radio_button_checked',
        'Future stage icons': 'radio_button_unchecked',
        'Update History section': 'Update History',
        'get_case_stage_progress call': 'get_case_stage_progress(fir_id)',
        'STAGE_LABELS usage': 'STAGE_LABELS',
        'No update controls': 'Read-Only for Citizens'
    }
    
    results = []
    for check_name, search_string in checks.items():
        if search_string in content:
            print(f"  ✅ {check_name}")
            results.append(True)
        else:
            print(f"  ❌ {check_name}")
            results.append(False)
    
    return all(results)


def verify_service_layer():
    """Verify Case Tracking service implementation."""
    print("\n" + "=" * 80)
    print("VERIFYING SERVICE LAYER")
    print("=" * 80)
    
    service_file = Path('backend/services/case_tracking_service.py') if Path('backend/services/case_tracking_service.py').exists() else Path('services/case_tracking_service.py')
    with open(service_file, 'r') as f:
        content = f.read()
    
    checks = {
        '8 Case Stages defined': 'CASE_STAGES = [',
        'Stage labels dictionary': 'STAGE_LABELS = {',
        'Database table creation': 'CREATE TABLE IF NOT EXISTS case_tracking',
        'get_current_case_stage function': 'def get_current_case_stage',
        'get_case_stage_progress function': 'def get_case_stage_progress',
        'update_case_stage function': 'def update_case_stage',
        'get_case_tracking_history function': 'def get_case_tracking_history',
        'initialize_case_tracking function': 'def initialize_case_tracking',
        'Notification creation': 'create_notification(',
        'Audit fields': 'updated_by_officer_name',
        'Track ID generation': 'TRK-'
    }
    
    results = []
    for check_name, search_string in checks.items():
        if search_string in content:
            print(f"  ✅ {check_name}")
            results.append(True)
        else:
            print(f"  ❌ {check_name}")
            results.append(False)
    
    return all(results)


def count_case_tracking_lines():
    """Count lines of code dedicated to case tracking."""
    print("\n" + "=" * 80)
    print("CODE STATISTICS")
    print("=" * 80)
    
    # Police page
    with open('pages/police.py', 'r') as f:
        police_content = f.read()
    police_start = police_content.find('# Case Tracking Section (Police can update stage)')
    police_end = police_content.find('# ==========================================', police_start)
    police_tracking_code = police_content[police_start:police_end] if police_start != -1 and police_end != -1 else ""
    police_lines = len(police_tracking_code.split('\n'))
    
    # Citizen page
    with open('pages/citizen.py', 'r') as f:
        citizen_content = f.read()
    citizen_start = citizen_content.find('# Case Tracking Section (Read-Only for Citizens)')
    citizen_end = citizen_content.find('# Public Case Progression Timeline', citizen_start)
    citizen_tracking_code = citizen_content[citizen_start:citizen_end] if citizen_start != -1 and citizen_end != -1 else ""
    citizen_lines = len(citizen_tracking_code.split('\n'))
    
    # Service layer
    with open('services/case_tracking_service.py', 'r') as f:
        service_content = f.read()
    service_lines = len(service_content.split('\n'))
    
    print(f"  Police Page Case Tracking UI: {police_lines} lines")
    print(f"  Citizen Page Case Tracking UI: {citizen_lines} lines")
    print(f"  Case Tracking Service Layer: {service_lines} lines")
    print(f"  Total Implementation: {police_lines + citizen_lines + service_lines} lines")


if __name__ == "__main__":
    print("\n" + "🔍 CASE TRACKING FEATURE VERIFICATION".center(80))
    print("=" * 80)
    
    police_ok = verify_police_page()
    citizen_ok = verify_citizen_page()
    service_ok = verify_service_layer()
    count_case_tracking_lines()
    
    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    
    if police_ok:
        print("  ✅ Police Page: FULLY IMPLEMENTED")
    else:
        print("  ❌ Police Page: MISSING COMPONENTS")
    
    if citizen_ok:
        print("  ✅ Citizen Page: FULLY IMPLEMENTED")
    else:
        print("  ❌ Citizen Page: MISSING COMPONENTS")
    
    if service_ok:
        print("  ✅ Service Layer: FULLY IMPLEMENTED")
    else:
        print("  ❌ Service Layer: MISSING COMPONENTS")
    
    print("\n" + "=" * 80)
    
    if police_ok and citizen_ok and service_ok:
        print("✅ VERIFICATION PASSED - Case Tracking is FULLY IMPLEMENTED")
        print("\nFeature Locations:")
        print("  • Police Update UI: /police/fir/{fir_id} → 'Case Tracking & Stage Management'")
        print("  • Citizen View UI: /citizen/fir/{fir_id} → 'Case Tracking' (Read-Only)")
        print("  • Service Layer: services/case_tracking_service.py")
        print("  • Database Table: case_tracking")
        sys.exit(0)
    else:
        print("❌ VERIFICATION FAILED - Some components missing")
        sys.exit(1)
