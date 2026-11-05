"""
Comprehensive Translation Generator for Online FIR Portal.
Generates complete translations for English (en), Kannada (kn), and Hindi (hi).
Applies legal/law enforcement domain terminology and cleans all mixed-language acronyms.
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from deep_translator import MyMemoryTranslator

TRANSLATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend', 'i18n', 'translations')

# Curated domain translations for police, legal, verification, and UI terms
DOMAIN_MAP_KN = {
    'ADMIN': 'ನಿರ್ವಾಹಕ',
    'ADMIN ONLY': 'ಕೇವಲ ನಿರ್ವಾಹಕರಿಗೆ',
    'ACTIVE & VERIFIED': 'ಸಕ್ರಿಯ ಮತ್ತು ಪರಿಶೀಲಿಸಲಾಗಿದೆ',
    'AFTER': 'ನಂತರ',
    'AFTER (New Content)': 'ನಂತರ (ಹೊಸ ವಿಷಯ)',
    'APPEND-ONLY LOG': 'ಸೇರ್ಪಡೆ-ಮಾತ್ರ ದಾಖಲೆ',
    'AUTHORIZED OFFICER ONLY': 'ಅಧಿಕೃತ ಅಧಿಕಾರಿಗೆ ಮಾತ್ರ',
    'AUTHORIZED_FIR_UPDATE': 'ಅಧಿಕೃತ ಎಫ್‌ಐಆರ್ ನವೀಕರಣ',
    'AUTHORIZED_OFFICER': 'ಅಧಿಕೃತ ಅಧಿಕಾರಿ',
    'Aadhaar Card': 'ಆಧಾರ್ ಕಾರ್ಡ್',
    'Access Denied: This section is restricted to Authorized Officers only.': 'ಪ್ರವೇಶ ನಿರಾಕರಿಸಲಾಗಿದೆ: ಈ ವಿಭಾಗವು ಅಧಿಕೃತ ಅಧಿಕಾರಿಗಳಿಗೆ ಮಾತ್ರ ಸೀಮಿತವಾಗಿದೆ.',
    'Access Denied: You do not have permission to view this case.': 'ಪ್ರವೇಶ ನಿರಾಕರಿಸಲಾಗಿದೆ: ಈ ಪ್ರಕರಣವನ್ನು ವೀಕ್ಷಿಸಲು ನಿಮಗೆ ಅನುಮತಿಯಿಲ್ಲ.',
    'Account Details': 'ಖಾತೆಯ ವಿವರಗಳು',
    'Accused / Suspect Details': 'ಆರೋಪಿ / ಶಂಕಿತರ ವಿವರಗಳು',
    'Action Type': 'ಕ್ರಮದ ಪ್ರಕಾರ',
    'Active Assigned Cases': 'ಸಕ್ರಿಯ ನಿಯೋಜಿತ ಪ್ರಕರಣಗಳು',
    'Admin Master Email *': 'ಅಡ್ಮಿನ್ ಮಾಸ್ಟರ್ ಇಮೇಲ್ *',
    'Administrative Access Granted for': 'ಆಡಳಿತಾತ್ಮಕ ಪ್ರವೇಶವನ್ನು ನೀಡಲಾಗಿದೆ:',
    'Administrative Control Center': 'ಆಡಳಿತಾತ್ಮಕ ನಿಯಂತ್ರಣ ಕೇಂದ್ರ',
    'Administrative Functions': 'ಆಡಳಿತಾತ್ಮಕ ಕಾರ್ಯಗಳು',
    'Administrator Passcode *': 'ನಿರ್ವಾಹಕರ ಪಾಸ್‌ಕೋಡ್ *',
    'Administrator access required.': 'ನಿರ್ವಾಹಕರ ಪ್ರವೇಶ ಅಗತ್ಯವಿದೆ.',
    'Alerts from higher officers, case reassignments, and new citizen chat messages will appear here.': 'ಹಿರಿಯ ಅಧಿಕಾರಿಗಳ ಎಚ್ಚರಿಕೆಗಳು, ಪ್ರಕರಣ ಮರುಹಂಚಿಕೆಗಳು ಮತ್ತು ಹೊಸ ನಾಗರಿಕ ಚಾಟ್ ಸಂದೇಶಗಳು ಇಲ್ಲಿ ಕಾಣಿಸಿಕೊಳ್ಳುತ್ತವೆ.',
    'Alerts on newly submitted citizen FIRs and case updates.': 'ಹೊಸದಾಗಿ ಸಲ್ಲಿಸಲಾದ ನಾಗರಿಕ ಎಫ್‌ಐಆರ್‌ಗಳು ಮತ್ತು ಪ್ರಕರಣ ನವೀಕರಣಗಳ ಕುರಿತು ಎಚ್ಚರಿಕೆಗಳು.',
    'All citizen-submitted FIRs have been verified and processed.': 'ನಾಗರಿಕರು ಸಲ್ಲಿಸಿದ ಎಲ್ಲಾ ಎಫ್‌ಐಆರ್‌ಗಳನ್ನು ಪರಿಶೀಲಿಸಲಾಗಿದೆ ಮತ್ತು ಪ್ರಕ್ರಿಯೆಗೊಳಿಸಲಾಗಿದೆ.',
    'Already registered?': 'ಈಗಾಗಲೇ ನೋಂದಾಯಿಸಲಾಗಿದೆಯೇ?',
    'An official FIR has already been created for this complaint.': 'ಈ ದೂರಿಗೆ ಈಗಾಗಲೇ ಅಧಿಕೃತ ಎಫ್‌ಐಆರ್ ರಚಿಸಲಾಗಿದೆ.',
    'Append-Only Audit Event Trail': 'ಸೇರ್ಪಡೆ-ಮಾತ್ರ ಆಡಿಟ್ ಈವೆಂಟ್ ಟ್ರಯಲ್',
    'Append-only event trails recorded across all FIR lifecycles.': 'ಎಲ್ಲಾ ಎಫ್‌ಐಆರ್ ಜೀವಿತಾವಧಿಗಳಲ್ಲಿ ದಾಖಲಾದ ಸೇರ್ಪಡೆ-ಮಾತ್ರ ಈವೆಂಟ್ ಟ್ರಯಲ್‌ಗಳು.',
    'Assign Investigating Police Officer': 'ತನಿಖಾ ಪೊಲೀಸ್ ಅಧಿಕಾರಿಯನ್ನು ನಿಯೋಜಿಸಿ',
    'Assign Officers to Open FIRs': 'ತೆರೆದ ಎಫ್‌ಐಆರ್‌ಗಳಿಗೆ ಅಧಿಕಾರಿಗಳನ್ನು ನಿಯೋಜಿಸಿ',
    'Assign Police Officer 👮': 'ಪೊಲೀಸ್ ಅಧಿಕಾರಿಯನ್ನು ನಿಯೋಜಿಸಿ 👮',
    'Assign lead investigating officers to incoming citizen FIRs.': 'ಬರುವ ನಾಗರಿಕ ಎಫ್‌ಐಆರ್‌ಗಳಿಗೆ ಮುಖ್ಯ ತನಿಖಾಧಿಕಾರಿಗಳನ್ನು ನಿಯೋಜಿಸಿ.',
    'Assigned Cases': 'ನಿಯೋಜಿತ ಪ್ರಕರಣಗಳು',
    'Assigned FIR Cases': 'ನಿಯೋಜಿತ ಎಫ್‌ಐಆರ್ ಪ್ರಕರಣಗಳು',
    'Assigned Investigating Officer': 'ನಿಯೋಜಿತ ತನಿಖಾಧಿಕಾರಿ',
    'Attach Evidence Documents': 'ಸಾಕ್ಷ್ಯಾಧಾರ ದಾಖಲೆಗಳನ್ನು ಲಗತ್ತಿಸಿ',
    'Audit Trail': 'ಆಡಿಟ್ ವಿವರ',
    'Audit Trail & Cryptographic Proofs': 'ಆಡಿಟ್ ಟ್ರಯಲ್ ಮತ್ತು ಕ್ರಿಪ್ಟೋಗ್ರಾಫಿಕ್ ಪುರಾವೆಗಳು',
    'Authorized Officer Portal': 'ಅಧಿಕೃತ ಅಧಿಕಾರಿಗಳ ಪೋರ್ಟಲ್',
    'Authorized Personnel Only': 'ಅಧಿಕೃತ ಸಿಬ್ಬಂದಿಗೆ ಮಾತ್ರ',
    'Badge ID': 'ಬ್ಯಾಡ್ಜ್ ಐಡಿ',
    'Blockchain Audit': 'ಬ್ಲಾಕ್‌ಚೈನ್ ಆಡಿಟ್',
    'Blockchain Proof Active': 'ಬ್ಲಾಕ್‌ಚೈನ್ ಪುರಾವೆ ಸಕ್ರಿಯವಾಗಿದೆ',
    'Camera / Photo Capture': 'ಕ್ಯಾಮೆರಾ / ಫೋಟೋ ಸೆರೆಹಿಡಿಯುವಿಕೆ',
    'Case Classification': 'ಪ್ರಕರಣ ವರ್ಗೀಕರಣ',
    'Case Description': 'ಪ್ರಕರಣದ ವಿವರಣೆ',
    'Case Progress Timeline': 'ಪ್ರಕರಣ ಪ್ರಗತಿಯ ಟೈಮ್‌ಲೈನ್',
    'Charge Sheet Filed': 'ದೋಷಾರೋಪ ಪಟ್ಟಿ ಸಲ್ಲಿಸಲಾಗಿದೆ',
    'Citizen Account': 'ನಾಗರಿಕ ಖಾತೆ',
    'Citizen Dashboard': 'ನಾಗರಿಕ ಡ್ಯಾಶ್‌ಬೋರ್ಡ್',
    'Citizen Login': 'ನಾಗರಿಕ ಲಾಗಿನ್',
    'Citizen Registration': 'ನಾಗರಿಕ ನೋಂದಣಿ',
    'Citizen Verification & Registration': 'ನಾಗರಿಕ ಪರಿಶೀಲನೆ ಮತ್ತು ನೋಂದಣಿ',
    'Closed / Disposed': 'ಮುಕ್ತಾಯಗೊಂಡಿದೆ / ಇತ್ಯರ್ಥವಾಗಿದೆ',
    'Complainant Details': 'ದೂರುದಾರರ ವಿವರಗಳು',
    'Complaint Reference': 'ದೂರು ಉಲ್ಲೇಖ',
    'Create Citizen Account': 'ನಾಗರಿಕ ಖಾತೆ ರಚಿಸಿ',
    'Create Citizen Account →': 'ನಾಗರಿಕ ಖಾತೆ ರಚಿಸಿ →',
    'Create Password *': 'ಪಾಸ್‌ವರ್ಡ್ ರಚಿಸಿ *',
    'Confirm Password *': 'ಪಾಸ್‌ವರ್ಡ್ ದೃಢೀಕರಿಸಿ *',
    'Cryptographic Security': 'ಕ್ರಿಪ್ಟೋಗ್ರಾಫಿಕ್ ಸುರಕ್ಷತೆ',
    'Cyber Crime': 'ಸೈಬರ್ ಅಪರಾಧ',
    'Digital FIR': 'ಡಿಜಿಟಲ್ ಎಫ್‌ಐಆರ್',
    'Driving License': 'ಚಾಲನಾ ಪರವಾನಗಿ',
    'Evidence & Witness': 'ಸಾಕ್ಷ್ಯಾಧಾರ ಮತ್ತು ಸಾಕ್ಷಿ',
    'File FIR Online': 'ಆನ್‌ಲೈನ್ ಎಫ್‌ಐಆರ್ ದಾಖಲಿಸಿ',
    'File Online FIR': 'ಆನ್‌ಲೈನ್ ಎಫ್‌ಐಆರ್ ದಾಖಲಿಸಿ',
    'Government ID': 'ಸರ್ಕಾರಿ ಗುರುತಿನ ಚೀಟಿ',
    'Government ID Type *': 'ಸರ್ಕಾರಿ ಗುರುತಿನ ಚೀಟಿ ಪ್ರಕಾರ *',
    'Government of Karnataka': 'ಕರ್ನಾಟಕ ಸರ್ಕಾರ',
    'Hearing Details': 'ವಿಚಾರಣೆಯ ವಿವರಗಳು',
    'Immediate Police Action Required': 'ತಕ್ಷಣದ ಪೊಲೀಸ್ ಕ್ರಮ ಅಗತ್ಯವಿದೆ',
    'Incident Date & Time *': 'ಘಟನೆಯ ದಿನಾಂಕ ಮತ್ತು ಸಮಯ *',
    'Incident Location *': 'ಘಟನೆಯ ಸ್ಥಳ *',
    'Investigating Officer': 'ತನಿಖಾಧಿಕಾರಿ',
    'Investigation In Progress': 'ತನಿಖೆ ಪ್ರಗತಿಯಲ್ಲಿದೆ',
    'Koramangala Police Station': 'ಕೋರಮಂಗಲ ಪೊಲೀಸ್ ಠಾಣೆ',
    'Indiranagar Police Station': 'ಇಂದಿರಾನಗರ ಪೊಲೀಸ್ ಠಾಣೆ',
    'Location Permission': 'ಸ್ಥಳದ ಅನುಮತಿ',
    'Mobile & OTP Verification': 'ಮೊಬೈಲ್ ಮತ್ತು ಒಟಿಪಿ ಪರಿಶೀಲನೆ',
    'Mobile Number *': 'ಮೊಬೈಲ್ ಸಂಖ್ಯೆ *',
    'Mock verification services active. All test data is pre-filled. Disabled in production.': 'ಅಣಕು ಪರಿಶೀಲನಾ ಸೇವೆಗಳು ಸಕ್ರಿಯವಾಗಿವೆ. ಎಲ್ಲಾ ಪರೀಕ್ಷಾ ಡೇಟಾವನ್ನು ಮೊದಲೇ ಭರ್ತಿ ಮಾಡಲಾಗಿದೆ. ಉತ್ಪಾದನೆಯಲ್ಲಿ ನಿಷ್ಕ್ರಿಯಗೊಳಿಸಲಾಗಿದೆ.',
    'My Assigned Cases': 'ನನ್ನ ನಿಯೋಜಿತ ಪ್ರಕರಣಗಳು',
    'My Assigned FIR Cases': 'ನನ್ನ ನಿಯೋಜಿತ ಎಫ್‌ಐಆರ್ ಪ್ರಕರಣಗಳು',
    'New FIR Submitted': 'ಹೊಸ ಎಫ್‌ಐಆರ್ ಸಲ್ಲಿಸಲಾಗಿದೆ',
    'No FIRs registered yet.': 'ಇನ್ನೂ ಯಾವುದೇ ಎಫ್‌ಐಆರ್‌ಗಳು ದಾಖಲಾಗಿಲ್ಲ.',
    'Official Case Description / Formatted Incident Statement *': 'ಅಧಿಕೃತ ಪ್ರಕರಣ ವಿವರಣೆ / ರಚನಾತ್ಮಕ ಘಟನಾ ಹೇಳಿಕೆ *',
    'Official FIR Number:': 'ಅಧಿಕೃತ ಎಫ್‌ಐಆರ್ ಸಂಖ್ಯೆ:',
    'Official Police Email / Badge ID *': 'ಅಧಿಕೃತ ಪೊಲೀಸ್ ಇಮೇಲ್ / ಬ್ಯಾಡ್ಜ್ ಐಡಿ *',
    'Officer Security Passcode *': 'ಅಧಿಕಾರಿಯ ಭದ್ರತಾ ಪಾಸ್‌ಕೋಡ್ *',
    'Online FIR Portal': 'ಆನ್‌ಲೈನ್ ಎಫ್‌ಐಆರ್ ಪೋರ್ಟಲ್',
    'PAN Card': 'ಪ್ಯಾನ್ ಕಾರ್ಡ್',
    'Passport': 'ಪಾಸ್‌ಪೋರ್ಟ್',
    'Pending Review': 'ಪರಿಶೀಲನೆ ಬಾಕಿ ಇದೆ',
    'Pending Verification': 'ಪರಿಶೀಲನೆ ಬಾಕಿ ಇದೆ',
    'Police Case Workspace': 'ಪೊಲೀಸ್ ಪ್ರಕರಣ ಕಾರ್ಯಸ್ಥಳ',
    'Police Officer Operations': 'ಪೊಲೀಸ್ ಅಧಿಕಾರಿ ಕಾರ್ಯಾಚರಣೆಗಳು',
    'Police Station / Unit *': 'ಪೊಲೀಸ್ ಠಾಣೆ / ವಿಭಾಗ *',
    'Quick Fill': 'ತ್ವರಿತ ಭರ್ತಿ',
    'Real-Time Status Notifications': 'ನೈಜ-ಸಮಯದ ಸ್ಥಿತಿ ಅಧಿಸೂಚನೆಗಳು',
    'Recent Officer Alerts & Messages': 'ಇತ್ತೀಚಿನ ಅಧಿಕಾರಿ ಎಚ್ಚರಿಕೆಗಳು ಮತ್ತು ಸಂದೇಶಗಳು',
    'Register Citizen Account': 'ನಾಗರಿಕ ಖಾತೆ ನೋಂದಾಯಿಸಿ',
    'Resolved / Chargesheeted': 'ಪರಿಹರಿಸಲಾಗಿದೆ / ದೋಷಾರೋಪ ಪಟ್ಟಿ ಸಲ್ಲಿಸಲಾಗಿದೆ',
    'Return to Citizen Portal': 'ನಾಗರಿಕ ಪೋರ್ಟಲ್‌ಗೆ ಹಿಂತಿರುಗಿ',
    'Secure · Official · Government Verified': 'ಸುರಕ್ಷಿತ · ಅಧಿಕೃತ · ಸರ್ಕಾರದಿಂದ ಪರಿಶೀಲಿಸಲ್ಪಟ್ಟಿದೆ',
    'Send OTP': 'ಒಟಿಪಿ ಕಳುಹಿಸಿ',
    'Session Audit Record': 'ಅಧಿವೇಶನ ಆಡಿಟ್ ದಾಖಲೆ',
    'Sign In Here': 'ಇಲ್ಲಿ ಸೈನ್ ಇನ್ ಮಾಡಿ',
    'Simulate Photo Capture (Test Mode)': 'ಫೋಟೋ ಸೆರೆಹಿಡಿಯುವಿಕೆಯನ್ನು ಅನುಕರಿಸಿ (ಪರೀಕ್ಷಾ ಮೋಡ್)',
    'Station Location for Audit Trail': 'ಆಡಿಟ್ ವಿವರಕ್ಕಾಗಿ ಠಾಣಾ ಸ್ಥಳ',
    'Status:': 'ಸ್ಥಿತಿ:',
    'Step 1 — Create Your Account': 'ಹಂತ 1 — ನಿಮ್ಮ ಖಾತೆಯನ್ನು ರಚಿಸಿ',
    'Step 1: Account Credentials': 'ಹಂತ 1: ಖಾತೆಯ ರುಜುವಾತುಗಳು',
    'Step 2: Government ID': 'ಹಂತ 2: ಸರ್ಕಾರಿ ಗುರುತಿನ ಚೀಟಿ',
    'Step 3: Mobile Number + OTP Verification': 'ಹಂತ 3: ಮೊಬೈಲ್ ಸಂಖ್ಯೆ + ಒಟಿಪಿ ಪರಿಶೀಲನೆ',
    'Step 4: Camera / Photo Capture': 'ಹಂತ 4: ಕ್ಯಾಮೆರಾ / ಫೋಟೋ ಸೆರೆಹಿಡಿಯುವಿಕೆ',
    'Step 5: Location Permission': 'ಹಂತ 5: ಸ್ಥಳದ ಅನುಮತಿ',
    'Suspect / Accused Details': 'ಶಂಕಿತ / ಆರೋಪಿಗಳ ವಿವರಗಳು',
    'Tamper-Evident Blockchain Proof Platform': 'ಬದಲಾವಣೆ-ನಿರೋಧಕ ಬ್ಲಾಕ್‌ಚೈನ್ ಪುರಾವೆ ವೇದಿಕೆ',
    'Tamper-Evident Hashing': 'ಬದಲಾವಣೆ-ಗುರುತಿಸುವ ಹ್ಯಾಶಿಂಗ್',
    'Test / Demo Mode': 'ಪರೀಕ್ಷಾ / ಡೆಮೊ ಮೋಡ್',
    'Under Investigation': 'ತನಿಖೆ ಹಂತದಲ್ಲಿದೆ',
    'Verification Officer Desk': 'ಪರಿಶೀಲನಾ ಅಧಿಕಾರಿಗಳ ಡೆಸ್ಕ್',
    'Verify Officer Credentials & Enter ✦': 'ಅಧಿಕಾರಿಯ ರುಜುವಾತುಗಳನ್ನು ಪರಿಶೀಲಿಸಿ ಮತ್ತು ಪ್ರವೇಶಿಸಿ ✦',
    'View All →': 'ಎಲ್ಲಾ ವೀಕ್ಷಿಸಿ →',
    'Voter ID Card': 'ಮತದಾರರ ಗುರುತಿನ ಚೀಟಿ',
    'Why location access is required:': 'ಸ್ಥಳ ಪ್ರವೇಶ ಏಕೆ ಅಗತ್ಯವಿದೆ:',
    'Why mobile verification is required:': 'ಮೊಬೈಲ್ ಪರಿಶೀಲನೆ ಏಕೆ ಅಗತ್ಯವಿದೆ:',
    'Why we collect this information:': 'ನಾವು ಈ ಮಾಹಿತಿಯನ್ನು ಏಕೆ ಸಂಗ್ರಹಿಸುತ್ತೇವೆ:',
    'Witness & Evidence References': 'ಸಾಕ್ಷಿ ಮತ್ತು ಸಾಕ್ಷ್ಯಾಧಾರಗಳ ಉಲ್ಲೇಖಗಳು',
    'Your Citizen Account has been created.': 'ನಿಮ್ಮ ನಾಗರಿಕ ಖಾತೆಯನ್ನು ರಚಿಸಲಾಗಿದೆ.',
    '⚡ Quick Fill — Test Citizen': '⚡ ತ್ವರಿತ ಭರ್ತಿ — ಪರೀಕ್ಷಾ ನಾಗರಿಕ',
    '🔒 Session Audit Record': '🔒 ಅಧಿವೇಶನ ಆಡಿಟ್ ದಾಖಲೆ',
    '📍 Allow Location Access': '📍 ಸ್ಥಳ ಪ್ರವೇಶವನ್ನು ಅನುಮತಿಸಿ',
    '📍 Capture Station Location': '📍 ಠಾಣೆಯ ಸ್ಥಳವನ್ನು ಸೆರೆಹಿಡಿಯಿರಿ',
    '📍 Location not captured — will use station default.': '📍 ಸ್ಥಳ ಸೆರೆಹಿಡಿಯಲಾಗಿಲ್ಲ — ಠಾಣಾ ಡೀಫಾಲ್ಟ್ ಬಳಸಲಾಗುತ್ತದೆ.',
    '🧪 Mock Station Location': '🧪 ಅಣಕು ಠಾಣಾ ಸ್ಥಳ',
    '🧪 TEST / DEMO MODE ACTIVE': '🧪 ಪರೀಕ್ಷಾ / ಡೆಮೊ ಮೋಡ್ ಸಕ್ರಿಯವಾಗಿದೆ',
    '🧪 TEST / DEMO MODE': '🧪 ಪರೀಕ್ಷಾ / ಡೆಮೊ ಮೋಡ್',
    '📸 Capture Photo (Camera Access Required)': '📸 ಫೋಟೋ ಸೆರೆಹಿಡಿಯಿರಿ (ಕ್ಯಾಮೆರಾ ಪ್ರವೇಶ ಅಗತ್ಯವಿದೆ)',
    '1. Official FIR Number:': '1. ಅಧಿಕೃತ ಎಫ್‌ಐಆರ್ ಸಂಖ್ಯೆ:',
    '2. Citizen Tracking Reference:': '2. ನಾಗರಿಕ ಟ್ರ್ಯಾಕಿಂಗ್ ಉಲ್ಲೇಖ ಸಂಖ್ಯೆ:',
    '3. Police Station Jurisdiction:': '3. ಪೊಲೀಸ್ ಠಾಣಾ ವ್ಯಾಪ್ತಿ:',
    '4. Registration Date & Time:': '4. ನೋಂದಣಿ ದಿನಾಂಕ ಮತ್ತು ಸಮಯ:',
    '5. Complainant / Informant Details': '5. ದೂರುದಾರ / ಮಾಹಿತಿ ನೀಡಿದವರ ವಿವರಗಳು',
    '6. Incident Classification & Location Matrix': '6. ಘಟನೆಯ ವರ್ಗೀಕರಣ ಮತ್ತು ಸ್ಥಳ ಮಾಪನ',
    '7. Official Case Description & Statement of Fact': '7. ಅಧಿಕೃತ ಪ್ರಕರಣ ವಿವರಣೆ ಮತ್ತು ಘಟನಾ ಹೇಳಿಕೆ',
    '8. Suspect / Accused Details': '8. ಶಂಕಿತ / ಆರೋಪಿಗಳ ವಿವರಗಳು',
    '9. Witness & Evidence References': '9. ಸಾಕ್ಷಿ ಮತ್ತು ಸಾಕ್ಷ್ಯಾಧಾರಗಳ ಉಲ್ಲೇಖಗಳು',
    '10. Departmental Verification & Officer Assignment Seal': '10. ಇಲಾಖಾ ಪರಿಶೀಲನೆ ಮತ್ತು ಅಧಿಕಾರಿ ನಿಯೋಜನಾ ಮುದ್ರೆ'
}

DOMAIN_MAP_HI = {
    'ADMIN': 'व्यवस्थापक',
    'ADMIN ONLY': 'केवल व्यवस्थापक के लिए',
    'ACTIVE & VERIFIED': 'सक्रिय एवं सत्यापित',
    'AFTER': 'बाद में',
    'AFTER (New Content)': 'बाद में (नई सामग्री)',
    'APPEND-ONLY LOG': 'केवल-परिशिष्ट लॉग',
    'AUTHORIZED OFFICER ONLY': 'केवल अधिकृत अधिकारी के लिए',
    'AUTHORIZED_FIR_UPDATE': 'अधिकृत प्राथमिकी अद्यतन',
    'AUTHORIZED_OFFICER': 'अधिकृत अधिकारी',
    'Aadhaar Card': 'आधार कार्ड',
    'Access Denied: This section is restricted to Authorized Officers only.': 'प्रवेश अस्वीकृत: यह अनुभाग केवल अधिकृत अधिकारियों के लिए प्रतिबंधित है।',
    'Access Denied: You do not have permission to view this case.': 'प्रवेश अस्वीकृत: आपको इस मामले को देखने की अनुमति नहीं है।',
    'Account Details': 'खाता विवरण',
    'Accused / Suspect Details': 'आरोपी / संदिग्ध का विवरण',
    'Action Type': 'कार्रवाई का प्रकार',
    'Active Assigned Cases': 'सक्रिय सौंपे गए मामले',
    'Admin Master Email *': 'एडमिन मास्टर ईमेल *',
    'Administrative Access Granted for': 'प्रशासनिक पहुंच प्रदान की गई:',
    'Administrative Control Center': 'प्रशासनिक नियंत्रण केंद्र',
    'Administrative Functions': 'प्रशासनिक कार्य',
    'Administrator Passcode *': 'व्यवस्थापक पासकोड *',
    'Administrator access required.': 'व्यवस्थापक पहुंच आवश्यक है।',
    'Alerts from higher officers, case reassignments, and new citizen chat messages will appear here.': 'उच्च अधिकारियों के अलर्ट, केस पुनर्मूल्यांकन और नए नागरिक चैट संदेश यहां दिखाई देंगे।',
    'Alerts on newly submitted citizen FIRs and case updates.': 'नए जमा किए गए नागरिक प्राथमिकियों और केस अपडेट पर अलर्ट।',
    'All citizen-submitted FIRs have been verified and processed.': 'नागरिकों द्वारा दर्ज सभी प्राथमिकियों को सत्यापित और संसाधित किया गया है।',
    'Already registered?': 'क्या आप पहले से पंजीकृत हैं?',
    'An official FIR has already been created for this complaint.': 'इस शिकायत के लिए पहले से ही एक आधिकारिक प्राथमिकी दर्ज की जा चुकी है।',
    'Append-Only Audit Event Trail': 'केवल-परिशिष्ट ऑडिट इवेंट ट्रेल',
    'Append-only event trails recorded across all FIR lifecycles.': 'सभी प्राथमिकी चक्रों में दर्ज केवल-परिशिष्ट इवेंट ट्रेल्स।',
    'Assign Investigating Police Officer': 'जांच पुलिस अधिकारी नियुक्त करें',
    'Assign Officers to Open FIRs': 'खुली प्राथमिकियों के लिए अधिकारियों को नियुक्त करें',
    'Assign Police Officer 👮': 'पुलिस अधिकारी नियुक्त करें 👮',
    'Assign lead investigating officers to incoming citizen FIRs.': 'आने वाली नागरिक प्राथमिकियों के लिए मुख्य जांच अधिकारी नियुक्त करें।',
    'Assigned Cases': 'सौंपे गए मामले',
    'Assigned FIR Cases': 'सौंपे गए प्राथमिकी मामले',
    'Assigned Investigating Officer': 'सौंपा गया जांच अधिकारी',
    'Attach Evidence Documents': 'साक्ष्य दस्तावेज संलग्न करें',
    'Audit Trail': 'ऑडिट ट्रेल',
    'Audit Trail & Cryptographic Proofs': 'ऑडिट ट्रेल और क्रिप्टोग्राफिक प्रमाण',
    'Authorized Officer Portal': 'अधिकृत अधिकारी पोर्टल',
    'Authorized Personnel Only': 'केवल अधिकृत कर्मियों के लिए',
    'Badge ID': 'बैज आईडी',
    'Blockchain Audit': 'ब्लॉकचेन ऑडिट',
    'Blockchain Proof Active': 'ब्लॉकचेन प्रमाण सक्रिय है',
    'Camera / Photo Capture': 'कैमरा / फोटो खींचें',
    'Case Classification': 'मामला वर्गीकरण',
    'Case Description': 'मामले का विवरण',
    'Case Progress Timeline': 'केस प्रगति की समयरेखा',
    'Charge Sheet Filed': 'आरोप पत्र दाखिल',
    'Citizen Account': 'नागरिक खाता',
    'Citizen Dashboard': 'नागरिक डैशबोर्ड',
    'Citizen Login': 'नागरिक लॉगिन',
    'Citizen Registration': 'नागरिक पंजीकरण',
    'Citizen Verification & Registration': 'नागरिक सत्यापन एवं पंजीकरण',
    'Closed / Disposed': 'बंद / निस्तारित',
    'Complainant Details': 'शिकायतकर्ता का विवरण',
    'Complaint Reference': 'शिकायत संदर्भ',
    'Create Citizen Account': 'नागरिक खाता बनाएं',
    'Create Citizen Account →': 'नागरिक खाता बनाएं →',
    'Create Password *': 'पासवर्ड बनाएं *',
    'Confirm Password *': 'पासवर्ड की पुष्टि करें *',
    'Cryptographic Security': 'क्रिप्टोग्राफिक सुरक्षा',
    'Cyber Crime': 'साइबर अपराध',
    'Digital FIR': 'डिजिटल प्राथमिकी',
    'Driving License': 'ड्राइविंग लाइसेंस',
    'Evidence & Witness': 'साक्ष्य एवं गवाह',
    'File FIR Online': 'ऑनलाइन प्राथमिकी दर्ज करें',
    'File Online FIR': 'ऑनलाइन प्राथमिकी दर्ज करें',
    'Government ID': 'सरकारी पहचान पत्र',
    'Government ID Type *': 'सरकारी पहचान पत्र का प्रकार *',
    'Government of Karnataka': 'कर्नाटक सरकार',
    'Hearing Details': 'सुनवाई का विवरण',
    'Immediate Police Action Required': 'तत्काल पुलिस कार्रवाई आवश्यक',
    'Incident Date & Time *': 'घटना की तारीख और समय *',
    'Incident Location *': 'घटना का स्थान *',
    'Investigating Officer': 'जांच अधिकारी',
    'Investigation In Progress': 'जांच प्रगति पर है',
    'Koramangala Police Station': 'कोरमंगला पुलिस स्टेशन',
    'Indiranagar Police Station': 'इंदिरानगर पुलिस स्टेशन',
    'Location Permission': 'स्थान की अनुमति',
    'Mobile & OTP Verification': 'मोबाइल और ओटीपी सत्यापन',
    'Mobile Number *': 'मोबाइल नंबर *',
    'Mock verification services active. All test data is pre-filled. Disabled in production.': 'मॉक सत्यापन सेवाएं सक्रिय हैं। सभी परीक्षण डेटा पहले से भरे हुए हैं। उत्पादन में अक्षम।',
    'My Assigned Cases': 'मेरे सौंपे गए मामले',
    'My Assigned FIR Cases': 'मेरे सौंपे गए प्राथमिकी मामले',
    'New FIR Submitted': 'नई प्राथमिकी दर्ज की गई',
    'No FIRs registered yet.': 'अभी तक कोई प्राथमिकी दर्ज नहीं की गई है।',
    'Official Case Description / Formatted Incident Statement *': 'आधिकारिक मामला विवरण / संरचित घटना विवरण *',
    'Official FIR Number:': 'आधिकारिक प्राथमिकी संख्या:',
    'Official Police Email / Badge ID *': 'आधिकारिक पुलिस ईमेल / बैज आईडी *',
    'Officer Security Passcode *': 'अधिकारी सुरक्षा पासकोड *',
    'Online FIR Portal': 'ऑनलाइन प्राथमिकी पोर्टल',
    'PAN Card': 'पैन कार्ड',
    'Passport': 'पासपोर्ट',
    'Pending Review': 'समीक्षा लंबित',
    'Pending Verification': 'सत्यापन लंबित',
    'Police Case Workspace': 'पुलिस केस कार्यक्षेत्र',
    'Police Officer Operations': 'पुलिस अधिकारी संचालन',
    'Police Station / Unit *': 'पुलिस स्टेशन / इकाई *',
    'Quick Fill': 'त्वरित भरें',
    'Real-Time Status Notifications': 'वास्तविक समय स्थिति सूचनाएं',
    'Recent Officer Alerts & Messages': 'अधिकारी के हालिया अलर्ट और संदेश',
    'Register Citizen Account': 'नागरिक खाता पंजीकृत करें',
    'Resolved / Chargesheeted': 'हल किया गया / आरोप पत्र दाखिल',
    'Return to Citizen Portal': 'नागरिक पोर्टल पर लौटें',
    'Secure · Official · Government Verified': 'सुरक्षित · आधिकारिक · सरकार द्वारा सत्यापित',
    'Send OTP': 'ओटीपी भेजें',
    'Session Audit Record': 'सत्र ऑडिट रिकॉर्ड',
    'Sign In Here': 'यहाँ साइन इन करें',
    'Simulate Photo Capture (Test Mode)': 'फोटो खींचने का अनुकरण करें (परीक्षण मोड)',
    'Station Location for Audit Trail': 'ऑडिट ट्रेल के लिए स्टेशन का स्थान',
    'Status:': 'स्थिति:',
    'Step 1 — Create Your Account': 'चरण 1 — अपना खाता बनाएं',
    'Step 1: Account Credentials': 'चरण 1: खाते के क्रेडेंशियल्स',
    'Step 2: Government ID': 'चरण 2: सरकारी पहचान पत्र',
    'Step 3: Mobile Number + OTP Verification': 'चरण 3: मोबाइल नंबर + ओटीपी सत्यापन',
    'Step 4: Camera / Photo Capture': 'चरण 4: कैमरा / फोटो खींचें',
    'Step 5: Location Permission': 'चरण 5: स्थान की अनुमति',
    'Suspect / Accused Details': 'संदिग्ध / आरोपी का विवरण',
    'Tamper-Evident Blockchain Proof Platform': 'छेड़छाड़-रोधी ब्लॉकचेन प्रमाण मंच',
    'Tamper-Evident Hashing': 'छेड़छाड़-रोधी हैशिंग',
    'Test / Demo Mode': 'परीक्षण / डेमो मोड',
    'Under Investigation': 'जांच जारी है',
    'Verification Officer Desk': 'सत्यापन अधिकारी डेस्क',
    'Verify Officer Credentials & Enter ✦': 'अधिकारी क्रेडेंशियल्स सत्यापित करें और प्रवेश करें ✦',
    'View All →': 'सभी देखें →',
    'Voter ID Card': 'मतदाता पहचान पत्र',
    'Why location access is required:': 'स्थान की अनुमति क्यों आवश्यक है:',
    'Why mobile verification is required:': 'मोबाइल सत्यापन क्यों आवश्यक है:',
    'Why we collect this information:': 'हम यह जानकारी क्यों एकत्र करते हैं:',
    'Witness & Evidence References': 'गवाह और साक्ष्य संदर्भ',
    'Your Citizen Account has been created.': 'आपका नागरिक खाता सफलतापूर्वक बना दिया गया है।',
    '⚡ Quick Fill — Test Citizen': '⚡ त्वरित भरें — परीक्षण नागरिक',
    '🔒 Session Audit Record': '🔒 सत्र ऑडिट रिकॉर्ड',
    '📍 Allow Location Access': '📍 स्थान अनुमति दें',
    '📍 Capture Station Location': '📍 स्टेशन का स्थान प्राप्त करें',
    '📍 Location not captured — will use station default.': '📍 स्थान प्राप्त नहीं हुआ — स्टेशन डिफ़ॉल्ट का उपयोग किया जाएगा।',
    '🧪 Mock Station Location': '🧪 परीक्षण स्टेशन स्थान',
    '🧪 TEST / DEMO MODE ACTIVE': '🧪 परीक्षण / डेमो मोड सक्रिय',
    '🧪 TEST / DEMO MODE': '🧪 परीक्षण / डेमो मोड',
    '📸 Capture Photo (Camera Access Required)': '📸 फोटो खींचें (कैमरा अनुमति आवश्यक)',
    '1. Official FIR Number:': '1. आधिकारिक प्राथमिकी संख्या:',
    '2. Citizen Tracking Reference:': '2. नागरिक ट्रैकिंग संदर्भ संख्या:',
    '3. Police Station Jurisdiction:': '3. पुलिस स्टेशन क्षेत्राधिकार:',
    '4. Registration Date & Time:': '4. पंजीकरण तिथि और समय:',
    '5. Complainant / Informant Details': '5. शिकायतकर्ता / सूचनाकर्ता का विवरण',
    '6. Incident Classification & Location Matrix': '6. घटना का वर्गीकरण और स्थान मैट्रिक्स',
    '7. Official Case Description & Statement of Fact': '7. आधिकारिक मामला विवरण और घटना का विवरण',
    '8. Suspect / Accused Details': '8. संदिग्ध / आरोपी का विवरण',
    '9. Witness & Evidence References': '9. गवाह और साक्ष्य संदर्भ',
    '10. Departmental Verification & Officer Assignment Seal': '10. विभागीय सत्यापन और अधिकारी नियुक्ति मुहर'
}


def clean_postprocess(text: str, lang: str) -> str:
    """Eliminate all remaining English abbreviations and terms from Kannada and Hindi translations."""
    if not text or not isinstance(text, str):
        return text or ''
    if lang == 'kn':
        text = re.sub(r'e-FIR|eFIR', 'ಇ-ಎಫ್‌ಐಆರ್', text, flags=re.I)
        text = re.sub(r'FIRಗಳು|FIRs', 'ಎಫ್‌ಐಆರ್‌ಗಳು', text)
        text = re.sub(r'FIRಗೆ', 'ಎಫ್‌ಐಆರ್‌ಗೆ', text)
        text = re.sub(r'FIRಯನ್ನು', 'ಎಫ್‌ಐಆರ್ ಅನ್ನು', text)
        text = re.sub(r'FIRನಲ್ಲಿ', 'ಎಫ್‌ಐಆರ್‌ನಲ್ಲಿ', text)
        text = re.sub(r'FIRನ', 'ಎಫ್‌ಐಆರ್‌ನ', text)
        text = re.sub(r'\bFIR\b', 'ಎಫ್‌ಐಆರ್', text)
        text = re.sub(r'Bengaluru Urban', 'ಬೆಂಗಳೂರು ನಗರ', text, flags=re.I)
        text = re.sub(r'Bengaluru Rural', 'ಬೆಂಗಳೂರು ಗ್ರಾಮಾಂತರ', text, flags=re.I)
        text = re.sub(r'Indiranagar', 'ಇಂದಿರಾನಗರ', text, flags=re.I)
        text = re.sub(r'Koramangala', 'ಕೋರಮಂಗಲ', text, flags=re.I)
        text = re.sub(r'Cyber Crime', 'ಸೈಬರ್ ಅಪರಾಧ', text, flags=re.I)
        text = text.replace(' & ', ' ಮತ್ತು ')
        text = text.replace('ADMIN ONLY', 'ಕೇವಲ ನಿರ್ವಾಹಕರಿಗೆ')
        text = text.replace('AUTHORIZED OFFICER ONLY', 'ಅಧಿಕೃತ ಅಧಿಕಾರಿಗೆ ಮಾತ್ರ')
    elif lang == 'hi':
        text = re.sub(r'e-FIR|eFIR', 'ई-प्राथमिकी', text, flags=re.I)
        text = re.sub(r'FIRें|FIRs', 'प्राथमिकियां', text)
        text = re.sub(r'FIRों', 'प्राथमिकियों', text)
        text = re.sub(r'\bFIR\b', 'प्राथमिकी', text)
        text = re.sub(r'Bengaluru Urban', 'बेंगलुरु शहरी', text, flags=re.I)
        text = re.sub(r'Bengaluru Rural', 'बेंगलुरु ग्रामीण', text, flags=re.I)
        text = re.sub(r'Indiranagar', 'इंदिरानगर', text, flags=re.I)
        text = re.sub(r'Koramangala', 'कोरमंगला', text, flags=re.I)
        text = re.sub(r'Cyber Crime', 'साइबर अपराध', text, flags=re.I)
        text = text.replace(' & ', ' और ')
        text = text.replace('ADMIN ONLY', 'केवल व्यवस्थापक')
        text = text.replace('AUTHORIZED OFFICER ONLY', 'केवल अधिकृत अधिकारी')
    return text


def main():
    with open('filtered_ui_strings.json', 'r', encoding='utf-8') as f:
        strings = json.load(f)

    en_path = os.path.join(TRANSLATIONS_DIR, 'en.json')
    kn_path = os.path.join(TRANSLATIONS_DIR, 'kn.json')
    hi_path = os.path.join(TRANSLATIONS_DIR, 'hi.json')

    with open(en_path, 'r', encoding='utf-8') as f:
        en_dict = json.load(f)
    with open(kn_path, 'r', encoding='utf-8') as f:
        kn_dict = json.load(f)
    with open(hi_path, 'r', encoding='utf-8') as f:
        hi_dict = json.load(f)

    # 1. First populate direct domain translations
    for k, v in DOMAIN_MAP_KN.items():
        kn_dict[k] = clean_postprocess(v, 'kn')
        en_dict[k] = k
    for k, v in DOMAIN_MAP_HI.items():
        hi_dict[k] = clean_postprocess(v, 'hi')
        en_dict[k] = k

    # Identify remaining items that still need translation
    needed = [s for s in strings if s not in kn_dict or s not in hi_dict]
    print(f"Total needed for API translation: {len(needed)}")

    kn_translator = MyMemoryTranslator(source='en-GB', target='kn-IN')
    hi_translator = MyMemoryTranslator(source='en-GB', target='hi-IN')

    def translate_item(s):
        kn_val = kn_dict.get(s)
        hi_val = hi_dict.get(s)
        
        # Translate Kannada if missing
        if not kn_val:
            try:
                raw_kn = kn_translator.translate(s)
                kn_val = clean_postprocess(raw_kn, 'kn')
            except Exception:
                kn_val = clean_postprocess(s, 'kn')
        else:
            kn_val = clean_postprocess(kn_val, 'kn')
            
        # Translate Hindi if missing
        if not hi_val:
            try:
                raw_hi = hi_translator.translate(s)
                hi_val = clean_postprocess(raw_hi, 'hi')
            except Exception:
                hi_val = clean_postprocess(s, 'hi')
        else:
            hi_val = clean_postprocess(hi_val, 'hi')

        return s, kn_val, hi_val

    # Translate with worker pool in small batches to preserve progress
    batch_size = 30
    for i in range(0, len(needed), batch_size):
        chunk = needed[i:i + batch_size]
        print(f"Translating chunk {i // batch_size + 1}/{(len(needed) + batch_size - 1) // batch_size} ({len(chunk)} items)...")
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(translate_item, item) for item in chunk]
            for f in as_completed(futures):
                orig, kn_res, hi_res = f.result()
                en_dict[orig] = orig
                kn_dict[orig] = kn_res
                hi_dict[orig] = hi_res

        # Save checkpoint
        with open(en_path, 'w', encoding='utf-8') as f:
            json.dump(en_dict, f, ensure_ascii=False, indent=2)
        with open(kn_path, 'w', encoding='utf-8') as f:
            json.dump(kn_dict, f, ensure_ascii=False, indent=2)
        with open(hi_path, 'w', encoding='utf-8') as f:
            json.dump(hi_dict, f, ensure_ascii=False, indent=2)
        print(f"Saved checkpoint! Total keys in kn.json: {len(kn_dict)}")
        time.sleep(0.5)

    # Post-process all existing keys as well to ensure 0 mixed-language words
    for k in list(kn_dict.keys()):
        kn_dict[k] = clean_postprocess(kn_dict[k], 'kn')
    for k in list(hi_dict.keys()):
        hi_dict[k] = clean_postprocess(hi_dict[k], 'hi')

    with open(en_path, 'w', encoding='utf-8') as f:
        json.dump(en_dict, f, ensure_ascii=False, indent=2)
    with open(kn_path, 'w', encoding='utf-8') as f:
        json.dump(kn_dict, f, ensure_ascii=False, indent=2)
    with open(hi_path, 'w', encoding='utf-8') as f:
        json.dump(hi_dict, f, ensure_ascii=False, indent=2)

    print(f"COMPLETED! Final counts -> en: {len(en_dict)}, kn: {len(kn_dict)}, hi: {len(hi_dict)}")


if __name__ == '__main__':
    main()
