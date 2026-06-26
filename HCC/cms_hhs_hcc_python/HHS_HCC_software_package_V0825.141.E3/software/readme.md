# Purpose
This program creates risk factor scores for a set of beneficiaries with ICD-10 diagnoses, National Drug Codes (NDCs), and Healthcare Common Procedure Coding System (HCPCS) codes. 

# Output
Scoring output contains all continued enrollee and new enrollee flags and variables for each person regardless of enrollment status, leaving the user to decide which variables are relevant for each person.

# User Run Steps

## 1.
Follow steps 1 and 2 in the `user_runbook.md` to ensure that all requirements are installed and configurable.

## 2.
Edit user-defined parameters in the `run_spec` variable within the `config.py` file, located in the local folder. The file has variables initialized such that the user is only expected to change the value of the following variables within the `run_spec` dictionary.

- **switch_edits** – a Boolean value indicating the use of MCE (Medicare Code Editor) age criteria when performing the ICD-10 mappings, see `run_spec` (a dictionary with keys indicating switch values) to indicate True or False  
- **date_format** – indicates the date format in the user-defined beneficiaries file, such that the string is a type of format recognized by the Python datetime library  
  - Example: `"%m/%d/%Y"` → `1/21/1950`  
  - Example: `"YYYYMMDD"` → `19500121`  
- **intermediate_variable_output_switches** – a dict indicating the desired intermediate variables to include in the final output; turning these switches on allows users to review the intermediate steps the software takes in preparing model inputs and outputs  
  - True = on  
  - False = off  

### Intermediate Variable Options
- **demographic_age_sex**: Demographic age/sex variables created by the software  
- **cc_assignments**: CCs created by the software (before hierarchies are applied)  
- **hcc_assignments**: HCCs created by the software (after hierarchies are applied), before model groupings are applied  
- **rxc_assignments**: RXCs created by the software (after hierarchies are applied)  
- **rxc_hcc_interactions**: RXC × HCC interactions created by the software  
- **hcc_groups_and_interactions**: HCC groups and HCC interactions created by the software  
- **hhs_hcc_assignments**: HHS HCCs created by the software (after hierarchies are applied and groupings applied)  
- **severe_and_transplant_indicators_and_interactions**: SEVERE and TRANSPLANT indicators, and interactions with HCC_CNT, created by the software  
- **adult_hcc_contingent_enrollment_indicators**: Adult models HCC-contingent enrollment duration indicators (HCC_ED1–HCC_ED6) created by the software  
- **infant_model_assignments_and_interactions**: Infant model maturity categories, severity level categories, and maturity by severity level interactions created by the software  

## 3.
Navigate to the local `./data/input/user_defined` folder and add data to the following files (empty files have been provided):

### PERSON.csv
Includes demographic and enrollment information with the following variables:

- **ID** – unique identifier, string or numeric (will programmatically be converted to a string for consistency)  
- **DOB** – string value following the format set in the config `run_spec` under `date_format`  
- **SEX** – integer value coded 1 for male and 2 for female  
- **AGE_LAST** – integer value representing age as of last day of enrollment in benefit year, 0 or greater, not missing  
- **METAL** – string value for enrollee’s plan level: platinum (P), gold (G), silver (S), bronze (B), catastrophic (C), not missing  
- **CSR_INDICATOR** – integer value 1–11, not missing; person-level indicator; enrollees who qualify for cost-sharing reductions or those enrolled in premium assistance Medicaid alternative plans will be assigned CSR_INDICATOR = 1–11; non-CSR recipients will be assigned CSR_INDICATOR = 1  
- **ENROLDURATION** – integer value 1–12 based on months enrolled in plan in benefit year as defined by days  

### DIAG.csv
A diagnosis file with at least one record per beneficiary, includes the following variables:

- **ID** – unique identifier, must be consistent with beneficiaries.csv  
- **DIAG** – string value with no special characters, user may include all diagnoses or limit the codes to those used by the model  
  - NOTE: ICD10 codes should be to the greatest level of available specificity. Diagnoses should be included only from acceptable sources.  
- **DIAGNOSIS_SERVICE_DATE** – string value following the format set in the config `run_spec` under `date_format`, not missing, provides the diagnosis’s service date  

### NDC.csv
A National Drug Code (NDC) file with at least one record per beneficiary, includes the following variables:

- **ID** – unique identifier, must be consistent with DIAG.csv  
- **NDC** – string value with no special characters  

### HCPCS.csv
A Healthcare Common Procedure Coding System (HCPCS) code file with at least one record per beneficiary, includes the following variables:

- **ID** – unique identifier, must be consistent with DIAG.csv  
- **HCPCS** – string value with no special characters  

## 4.
Run the program from the base package folder (the folder that contains the software folder) using the following command:

```bash
python ./software/HHS_HCC/transform.py
```

When the transform step is complete, locate the log for the program (./software/HHS_HCC/logs). The log file will contain print statements for each completed step and any error information. If errors occur, first check that the user-defined input data is in the correct format. If all steps run without errors, locate the final output data table located in the ./software/HHS_HCC/data/output folder.
