# Bugfix Requirements Document

## Introduction

This bugfix addresses the incorrect workflow where citizens can directly create FIRs without police verification. In a blockchain-based law enforcement system, FIRs (First Information Reports) are official legal documents that should only be created after proper police verification of complaints. Currently, the system incorrectly allows citizens to bypass the complaint verification workflow and create FIRs directly through the 7-step wizard at `/citizen/submit`.

The correct workflow should be:
1. Citizen files a complaint via `/citizen/complaints/new`
2. Police review and verify the complaint
3. Police officer creates an official FIR from the verified complaint
4. FIR is linked to the original complaint for traceability

## Bug Analysis

### Current Behavior (Defect)

**1.1** WHEN a citizen accesses `/citizen/submit` THEN the system allows direct FIR creation without police verification

**1.2** WHEN a citizen completes the 7-step FIR filing wizard THEN the system creates an FIR record with status "SUBMITTED" and assigns it directly to an officer

**1.3** WHEN a citizen files a complaint at `/citizen/complaints/new` THEN the system creates a complaint but provides no mechanism for police to convert it to an FIR

**1.4** WHEN the `firs` table schema is examined THEN there is no `complaint_id` field to link FIRs back to their originating complaints

**1.5** WHEN police officers review complaints THEN they cannot create official FIRs from verified complaints

### Expected Behavior (Correct)

**2.1** WHEN a citizen accesses `/citizen/submit` THEN the system SHALL redirect them to `/citizen/complaints/new` for filing a complaint instead

**2.2** WHEN a citizen attempts to create an FIR directly THEN the system SHALL prevent the action and show a message explaining that FIRs require police verification

**2.3** WHEN a police officer reviews a verified complaint THEN the system SHALL provide a "Create FIR from Complaint" action

**2.4** WHEN a police officer creates an FIR from a complaint THEN the system SHALL create an FIR record with the `complaint_id` field populated, linking it to the original complaint

**2.5** WHEN the `firs` table schema is modified THEN it SHALL include a `complaint_id` field to track the originating complaint

**2.6** WHEN a police officer creates an FIR from a complaint THEN the complaint status SHALL be updated to "FIR_CREATED"

**2.7** WHEN a citizen views their complaint after FIR creation THEN the system SHALL display the linked FIR number for tracking

### Unchanged Behavior (Regression Prevention)

**3.1** WHEN a citizen files a complaint at `/citizen/complaints/new` with valid data THEN the system SHALL CONTINUE TO create a complaint record with status "SUBMITTED"

**3.2** WHEN a police officer is assigned to a complaint THEN the system SHALL CONTINUE TO update the complaint status to "ASSIGNED"

**3.3** WHEN an existing FIR (created before this fix) is accessed THEN the system SHALL CONTINUE TO display and function normally even if `complaint_id` is NULL

**3.4** WHEN citizens view their submitted complaints list at `/citizen/complaints` THEN the system SHALL CONTINUE TO display all their complaints with correct status badges

**3.5** WHEN police officers view FIRs in their dashboard THEN the system SHALL CONTINUE TO show all FIRs with existing functionality for investigation and updates

**3.6** WHEN blockchain integrity verification is performed on FIRs THEN the system SHALL CONTINUE TO validate cryptographic hashes and version history correctly

**3.7** WHEN an officer updates an existing FIR THEN the system SHALL CONTINUE TO create immutable version records with blockchain audit trails
