# Requirements Document

## Introduction

This document specifies the requirements for a complete real-time citizen complaint submission and police verification workflow for an existing e-FIR law enforcement portal. The system enables citizens to submit complaints with supporting evidence, allows police officers to review and verify complaints in real-time, manages the FIR registration workflow with multiple status transitions, and provides real-time status tracking for citizens. The workflow integrates into the existing NiceGUI Python web application with blockchain-based FIR integrity verification.

## Glossary

- **Citizen_Portal**: The web interface accessible to citizens for complaint submission and status tracking
- **Police_Dashboard**: The real-time web interface accessible to police officers for reviewing and processing complaints
- **Complaint_System**: The backend service that stores and manages complaint data
- **Complaint_ID**: A unique identifier generated for each complaint submission
- **FIR_Number**: A unique identifier generated when an FIR is officially registered
- **Status_Engine**: The component that manages complaint status transitions and notifications
- **Authentication_Service**: The existing role-based access control system
- **Database_Service**: The existing database layer for data persistence
- **Evidence_Storage**: The file storage system for documents, images, and videos
- **Notification_Service**: The system that sends real-time updates to citizens and officers
- **Verification_Record**: The official police review and notes added to a complaint
- **Audit_Log**: The timestamped record of all status changes and user actions
- **Real_Time_Update**: An automatic UI refresh without manual page reload

## Requirements

### Requirement 1: Citizen Complaint Submission Interface

**User Story:** As a citizen, I want to submit a complaint through a web form, so that I can report incidents to law enforcement with all necessary details and evidence.

#### Acceptance Criteria

1. THE Citizen_Portal SHALL display a complaint submission form with fields for citizen name, contact details, complaint type, incident date, incident time, incident location, and complaint description
2. THE Citizen_Portal SHALL provide a file upload interface that accepts documents, images, and videos
3. WHEN a citizen submits a complaint form with all required fields, THE Complaint_System SHALL validate all inputs
4. WHEN input validation succeeds, THE Complaint_System SHALL generate a unique Complaint_ID
5. WHEN a Complaint_ID is generated, THE Complaint_System SHALL store the complaint data in the Database_Service
6. WHEN a complaint is stored, THE Complaint_System SHALL store all uploaded files in the Evidence_Storage
7. WHEN complaint submission is complete, THE Citizen_Portal SHALL display a confirmation message with the Complaint_ID
8. WHEN complaint submission is complete, THE Citizen_Portal SHALL display the initial status as "Submitted"
9. IF input validation fails, THEN THE Citizen_Portal SHALL display descriptive error messages for each invalid field

### Requirement 2: Complaint Data Persistence

**User Story:** As a system administrator, I want all complaint data securely stored in the database, so that data integrity is maintained and complaints can be retrieved reliably.

#### Acceptance Criteria

1. WHEN a complaint is submitted, THE Complaint_System SHALL store citizen name, contact details, complaint type, incident date, incident time, incident location, and description in the Database_Service
2. WHEN a complaint is submitted, THE Complaint_System SHALL store the submission timestamp in the Database_Service
3. WHEN a complaint is submitted, THE Complaint_System SHALL store file paths for all uploaded evidence in the Database_Service
4. WHEN a complaint is submitted, THE Complaint_System SHALL set the initial status to "Submitted" in the Database_Service
5. THE Complaint_System SHALL store all complaint data with referential integrity linking citizens, complaints, verification records, and FIRs
6. THE Complaint_System SHALL ensure all database write operations complete successfully before confirming submission

### Requirement 3: Real-Time Police Dashboard Display

**User Story:** As a police officer, I want to see newly submitted complaints appear automatically on my dashboard, so that I can respond promptly without manually refreshing the page.

#### Acceptance Criteria

1. WHEN a complaint is submitted, THE Police_Dashboard SHALL display the new complaint without manual page refresh
2. THE Police_Dashboard SHALL display Complaint_ID, citizen name, contact details, complaint type, incident date, incident time, incident location, and current status for each complaint
3. THE Police_Dashboard SHALL provide a mechanism to open the full complaint details view
4. THE Police_Dashboard SHALL provide a mechanism to download uploaded evidence files
5. THE Police_Dashboard SHALL update the displayed complaint list in real-time within 2 seconds of status changes
6. THE Police_Dashboard SHALL display complaints in reverse chronological order with newest submissions first

### Requirement 4: Complaint Details and Evidence Access

**User Story:** As a police officer, I want to view complete complaint information and access uploaded evidence, so that I can thoroughly review the case before making verification decisions.

#### Acceptance Criteria

1. WHEN a police officer opens a complaint details view, THE Police_Dashboard SHALL display all citizen-provided information including name, contact details, complaint type, incident date, incident time, location, and full description
2. WHEN a police officer opens a complaint details view, THE Police_Dashboard SHALL display a list of all uploaded evidence files with filenames
3. WHEN a police officer clicks on an evidence file, THE Police_Dashboard SHALL download the file to the officer's device
4. WHEN a police officer views a complaint, THE Police_Dashboard SHALL display the current status
5. WHEN a police officer views a complaint, THE Police_Dashboard SHALL display all existing verification notes

### Requirement 5: Complaint Status Management

**User Story:** As a police officer, I want to update complaint status and add verification notes, so that I can track the progress of complaints through the investigation workflow.

#### Acceptance Criteria

1. THE Status_Engine SHALL support the following status workflow: Submitted → Under Verification → Verified → FIR Registered → Investigation → Closed
2. THE Status_Engine SHALL support the following status workflow: Submitted → Under Verification → Rejected
3. WHEN a police officer selects a new status, THE Police_Dashboard SHALL provide an interface to add verification notes
4. WHEN a police officer confirms a status change, THE Status_Engine SHALL update the complaint status in the Database_Service
5. WHEN a status change occurs, THE Status_Engine SHALL store the timestamp of the change in the Audit_Log
6. WHEN a status change occurs, THE Status_Engine SHALL store the officer identity who made the change in the Audit_Log
7. WHEN a status change occurs, THE Status_Engine SHALL trigger a Real_Time_Update to the Police_Dashboard
8. WHEN a status change occurs, THE Status_Engine SHALL trigger a Real_Time_Update to the Citizen_Portal

### Requirement 6: Verification Notes Recording

**User Story:** As a police officer, I want to add official verification notes to complaints, so that I can document my review findings and communicate decisions.

#### Acceptance Criteria

1. THE Police_Dashboard SHALL provide a text input field for police officers to enter verification notes
2. WHEN a police officer adds verification notes, THE Complaint_System SHALL store the notes in the Database_Service linked to the complaint
3. WHEN verification notes are added, THE Complaint_System SHALL store the timestamp in the Database_Service
4. WHEN verification notes are added, THE Complaint_System SHALL store the officer identity in the Database_Service
5. THE Complaint_System SHALL preserve all historical verification notes without overwriting previous entries

### Requirement 7: FIR Registration Workflow

**User Story:** As an authorized police officer, I want to register an FIR for verified complaints, so that cases can proceed to formal investigation with official FIR numbers.

#### Acceptance Criteria

1. WHEN a complaint status is "Verified", THE Police_Dashboard SHALL display an FIR registration control
2. WHERE the current user has FIR registration authorization, THE Police_Dashboard SHALL enable the FIR registration control
3. WHEN an authorized officer initiates FIR registration, THE Complaint_System SHALL generate a unique FIR_Number
4. WHEN an FIR_Number is generated, THE Complaint_System SHALL store the FIR_Number in the Database_Service linked to the Complaint_ID
5. WHEN an FIR is registered, THE Complaint_System SHALL store the FIR registration timestamp in the Database_Service
6. WHEN an FIR is registered, THE Complaint_System SHALL store the authorized officer identity in the Database_Service
7. WHEN an FIR is registered, THE Status_Engine SHALL update the complaint status to "FIR Registered"
8. IF a complaint status is not "Verified", THEN THE Police_Dashboard SHALL disable the FIR registration control

### Requirement 8: Citizen Status Tracking Interface

**User Story:** As a citizen, I want to enter my Complaint_ID and see the current status in real-time, so that I can track the progress of my complaint without contacting the police station.

#### Acceptance Criteria

1. THE Citizen_Portal SHALL provide a complaint tracking page with a Complaint_ID input field
2. WHEN a citizen enters a valid Complaint_ID, THE Citizen_Portal SHALL retrieve the current complaint status from the Complaint_System
3. WHEN a citizen enters a valid Complaint_ID, THE Citizen_Portal SHALL display the status progression timeline
4. THE Citizen_Portal SHALL display status progression including: Complaint Submitted, Under Police Verification, Verified, FIR Registered, Investigation, and Closed
5. WHEN the complaint status changes, THE Citizen_Portal SHALL update the displayed status within 2 seconds without manual refresh
6. IF a citizen enters an invalid Complaint_ID, THEN THE Citizen_Portal SHALL display an error message indicating the complaint was not found

### Requirement 9: Role-Based Access Control

**User Story:** As a system administrator, I want role-based access control enforced throughout the system, so that citizens and police officers can only access authorized functions and data.

#### Acceptance Criteria

1. THE Authentication_Service SHALL authenticate citizens before allowing complaint submission
2. THE Authentication_Service SHALL authenticate police officers before allowing access to the Police_Dashboard
3. WHEN a citizen accesses complaint data, THE Authentication_Service SHALL verify the citizen owns the complaint
4. WHEN a police officer accesses complaint data, THE Authentication_Service SHALL verify the officer has appropriate permissions
5. THE Authentication_Service SHALL prevent citizens from modifying verification records
6. THE Authentication_Service SHALL prevent citizens from modifying FIR information
7. THE Authentication_Service SHALL prevent unauthorized users from accessing police-only functions
8. WHERE an officer has FIR registration authorization, THE Authentication_Service SHALL grant access to FIR registration functions
9. IF authentication fails, THEN THE Authentication_Service SHALL deny access and return an authentication error

### Requirement 10: Audit Log and Timestamp Recording

**User Story:** As a system administrator, I want all status changes recorded with timestamps and user identities, so that we maintain a complete audit trail for accountability and legal compliance.

#### Acceptance Criteria

1. WHEN a complaint is created, THE Audit_Log SHALL record the creation timestamp
2. WHEN a status changes to "Under Verification", THE Audit_Log SHALL record the timestamp and officer identity
3. WHEN a status changes to "Verified" or "Rejected", THE Audit_Log SHALL record the timestamp and officer identity
4. WHEN an FIR is registered, THE Audit_Log SHALL record the FIR registration timestamp and authorized officer identity
5. WHEN a status changes to "Investigation" or "Closed", THE Audit_Log SHALL record the timestamp and officer identity
6. THE Audit_Log SHALL store all historical status changes without deletion or overwriting
7. THE Audit_Log SHALL be immutable after recording to prevent tampering

### Requirement 11: Real-Time Notification System

**User Story:** As a citizen, I want to receive real-time notifications when my complaint status changes, so that I stay informed about the progress without checking repeatedly.

#### Acceptance Criteria

1. WHEN a complaint status changes, THE Notification_Service SHALL send a notification to the citizen who submitted the complaint
2. THE Notification_Service SHALL deliver notifications within 2 seconds of status change
3. THE Notification_Service SHALL include the Complaint_ID and new status in the notification message
4. THE Citizen_Portal SHALL display notifications without requiring page refresh
5. THE Notification_Service SHALL send notifications only to the citizen who owns the complaint

### Requirement 12: Integration with Existing System

**User Story:** As a developer, I want the complaint verification workflow integrated into the existing e-FIR portal, so that it reuses existing components and maintains consistent user experience.

#### Acceptance Criteria

1. THE Citizen_Portal SHALL reuse existing authentication mechanisms from the Authentication_Service
2. THE Complaint_System SHALL reuse the existing Database_Service for data persistence
3. THE Police_Dashboard SHALL reuse existing UI components and styling from the existing portal
4. THE Citizen_Portal SHALL reuse existing UI components and styling from the existing portal
5. THE Complaint_System SHALL integrate with the existing page routing system
6. THE Complaint_System SHALL maintain compatibility with the existing blockchain-based FIR integrity verification system
7. THE Complaint_System SHALL follow the existing project structure conventions for data modules, pages, and components

### Requirement 13: Responsive Design for Multiple Devices

**User Story:** As a user, I want the complaint submission and tracking interfaces to work on both desktop and mobile devices, so that I can access the system from any device.

#### Acceptance Criteria

1. THE Citizen_Portal SHALL render the complaint submission form responsively on desktop screens with width >= 1024 pixels
2. THE Citizen_Portal SHALL render the complaint submission form responsively on mobile screens with width < 768 pixels
3. THE Police_Dashboard SHALL render the complaint list responsively on desktop screens with width >= 1024 pixels
4. THE Police_Dashboard SHALL render the complaint list responsively on tablet screens with width between 768 and 1023 pixels
5. THE Citizen_Portal SHALL render the complaint tracking page responsively on all screen sizes
6. THE Citizen_Portal SHALL ensure all form controls are accessible via touch input on mobile devices
7. THE Police_Dashboard SHALL ensure all complaint actions are accessible via touch input on tablet devices

### Requirement 14: Evidence File Upload and Storage

**User Story:** As a citizen, I want to upload supporting documents, images, and videos with my complaint, so that I can provide evidence to support my case.

#### Acceptance Criteria

1. THE Citizen_Portal SHALL accept file uploads with extensions .pdf, .doc, .docx for documents
2. THE Citizen_Portal SHALL accept file uploads with extensions .jpg, .jpeg, .png, .gif for images
3. THE Citizen_Portal SHALL accept file uploads with extensions .mp4, .mov, .avi for videos
4. THE Citizen_Portal SHALL allow citizens to upload multiple files in a single complaint submission
5. WHEN a citizen uploads a file, THE Citizen_Portal SHALL validate the file extension
6. WHEN a citizen uploads a file exceeding 50 MB, THE Citizen_Portal SHALL display an error message indicating file size limit
7. WHEN file upload validation succeeds, THE Evidence_Storage SHALL store the file with a unique filename
8. WHEN file storage completes, THE Complaint_System SHALL store the file path in the Database_Service linked to the Complaint_ID
9. IF file upload validation fails, THEN THE Citizen_Portal SHALL display a descriptive error message

### Requirement 15: Status Timeline Visualization

**User Story:** As a citizen, I want to see a visual timeline of my complaint's status progression, so that I can understand what stage my complaint is at and what has already been completed.

#### Acceptance Criteria

1. THE Citizen_Portal SHALL display a status timeline with nodes for each status: Submitted, Under Verification, Verified/Rejected, FIR Registered, Investigation, Closed
2. THE Citizen_Portal SHALL visually indicate completed status nodes with a distinct styling
3. THE Citizen_Portal SHALL visually indicate the current status node with a distinct styling
4. THE Citizen_Portal SHALL visually indicate pending status nodes with a distinct styling
5. WHEN a status changes, THE Citizen_Portal SHALL update the timeline visualization within 2 seconds
6. THE Citizen_Portal SHALL display timestamps next to each completed status node
