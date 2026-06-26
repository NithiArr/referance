import os
from datetime import datetime
import sys

software_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..', 'software'))
if software_path not in sys.path:
    sys.path.insert(0, software_path)
    
from HHS_HCC.model_version_config import package_model_version
'''
Purpose: Define HHS HCC regression model scoring configurable and program-defined parameters.
Requires: User input for software specifications.
'''

'''
====================================================================
USER-DEFINED PARAMETERS
The user must configure the following parameters to meet software needs:

run_spec: dictionary defining software run specifications with variables for any user-defined parameters

    switch_edits: indicates the use of MCE (Medicare Code Editor) age criteria when performing the ICD-10 mappings
    
    date_format: indicates the date of birth format in the user-defined enrollee file, such that the string is a type of format
                recognized by the python datetime library, ie. an example of "%Y%m%d" would be 19500121, and 
                an example of "%m/%d/%Y" would be 1/21/1950
                
    intermediate_variable_output_switches: dictionary indicating which groups of intermediate variables the user would like to include in the final output
====================================================================
'''

run_spec = {
    # set to True to apply MCE age conditions during ICD-10 to CC mappings, False to not apply
    'switch_edits': True, 
    # set the format to reflect the format of dates, including DOB and diagnosis service date
    'date_format': "%Y%m%d", 
    # set to reflect desired intermediate variables in final output
    'intermediate_variable_output_switches': {
        # Demographic age/sex variables created by the software
        'demographic_age_sex': True,
        # CCs created by the software(before hierarchies are applied)
        'cc_assignments': True, 
        # HCCs created by the software (after hierarchies are applied), before model groupings are applied
        'hcc_assignments': True, 
        # RXCs created by the software (after hierarchies are applied)
        'rxc_assignments': True, 
        # RXC*HCC interactions created by the software
        'rxc_hcc_interactions': True,
        # HCC groups and HCC interactions created by the software
        'hcc_groups_and_interactions': True, 
        # HHS HCCs created by the software (after hierarchies are applied), after groupings are applied
        'hhs_hcc_assignments': True,
        # SEVERE and TRANSPLANT indicators, and interactions with HCC_CNT, created by the software
        'severe_and_transplant_indicators_and_interactions': True,
        # Adult models HCC-contingent enrollment duration indicators(HCC_ED1–HCC_ED6) created by the software
        'adult_hcc_contingent_enrollment_indicators': True,
        # Infant model maturity categories, severity level categories, and maturity by severity level interactions created by the software
        'infant_model_assignments_and_interactions': True
    }
}

''' 
====================================================================
DO NOT EDIT ANY REMAINING PARAMETERS
====================================================================
'''

'''
RTI PROGRAM-DEFINED PARAMETERS: user does not need to modify the following parameters
'''

model_name = "HHS_HCC"
# Note: model version imported from developer config
model_version_name = f"V0825.141.{package_model_version}"
base_folder = "software"
fiscal_year = 2026
benefit_year = 2025
run_spec['benefit_year'] = benefit_year
# Define cutoff date for diagnosis validations within the benefit year and within the current fiscal year
cutoff_date = datetime(benefit_year, 10, 1).date()
run_spec['cutoff_date'] = cutoff_date
# Define mapping cols for validating ICD10 diagnoses
run_spec['ICD10_is_valid_cols'] = [
    f"valid_ICD10_{benefit_year}",
    f"valid_ICD10_{fiscal_year}",
]

# Define user-defined input filenames
enrollee_input_filename = 'PERSON.csv'
diagnosis_input_filename = 'DIAGNOSES.csv'
hcpcs_input_filename = 'HCPCS.csv'
ndc_input_filename = 'NDC.csv'

# Define internal filenames
csr_table_filename = 'CSR_table.csv'
hcc_hierarchy_filename = 'HCC_hierarchy.csv'
HCPCS_mappings_filename = 'HCPCS_mappings.csv'
ICD10_mappings_filename = f'ICD10_HHS_CC_mappings_{fiscal_year}.csv'
NDC_mappings_filename = 'NDC_mappings.csv'
RXC_hierarchy_filename = 'RXC_hierarchy.csv'
RXC_interactions_filename = 'RXC_interactions.csv'
adult_factors_filename = 'adult_model_factors.csv'
adult_group_mappings_filename = 'adult_group_mappings.csv'
child_factors_filename = 'child_model_factors.csv'
child_group_mappings_filename = 'child_group_mappings.csv'
infant_factors_filename = 'infant_model_factors.csv'
infant_maturity_mappings_filename = 'infant_maturity_mappings.csv'
infant_severity_mappings_filename = 'infant_severity_mappings.csv'
severe_list_filename = 'severe_list.csv'
transplant_list_filename = 'transplant_list.csv'
bundled_mother_filename = 'bundled_mother_ICD10_codes.csv'
bundled_infant_filename = 'bundled_infant_ICD10_codes.csv'

# Define output filenames 
output_filename = f'{model_name}_{model_version_name}_scores.csv'
intermediates_output_filename = f'{model_name}_{model_version_name}_scores_and_intermediates.csv'

# Define filepaths
software_folderpath = f'./software/{model_name}'
log_output_filepath = os.path.join(software_folderpath + '/logs', f'{model_name}_{model_version_name}_transform_log.txt')
user_defined_data_basepath = f'{software_folderpath}/data/input/user_defined/'
internal_data_basepath = f'{software_folderpath}/data/input/internal/'
# NOTE: in package zip, all files from data sub folders will be moved into the single internal input data folder
output_data_basepath = f'{software_folderpath}/data/output/'
main_filepaths = {
    'enrollee_filepath': os.path.join(user_defined_data_basepath, enrollee_input_filename),
    'diagnoses_filepath': os.path.join(user_defined_data_basepath, diagnosis_input_filename),
    'hcpcs_filepath': os.path.join(user_defined_data_basepath, hcpcs_input_filename),
    'ndc_filepath': os.path.join(user_defined_data_basepath, ndc_input_filename),
    'csr_table_filepath': os.path.join(internal_data_basepath, csr_table_filename),
    'hcc_hierarchy_filepath': os.path.join(internal_data_basepath, hcc_hierarchy_filename),
    'HCPCS_mappings_filepath': os.path.join(internal_data_basepath, HCPCS_mappings_filename),
    'ICD10_mappings_filepath': os.path.join(internal_data_basepath, ICD10_mappings_filename),
    'NDC_mappings_filepath': os.path.join(internal_data_basepath, NDC_mappings_filename),
    'RXC_hierarchy_filepath': os.path.join(internal_data_basepath, RXC_hierarchy_filename),
    'RXC_interactions_filepath': os.path.join(internal_data_basepath, RXC_interactions_filename),
    'adult_factors_filepath': os.path.join(internal_data_basepath, adult_factors_filename),
    'adult_group_mappings_filepath': os.path.join(internal_data_basepath, adult_group_mappings_filename),
    'child_factors_filepath': os.path.join(internal_data_basepath, child_factors_filename), 
    'child_group_mappings_filepath': os.path.join(internal_data_basepath, child_group_mappings_filename),
    'infant_factors_filepath': os.path.join(internal_data_basepath, infant_factors_filename), 
    'infant_maturity_mappings_filepath': os.path.join(internal_data_basepath, infant_maturity_mappings_filename),
    'infant_severity_mappings_filepath': os.path.join(internal_data_basepath, infant_severity_mappings_filename),
    'severe_list_filepath': os.path.join(internal_data_basepath, severe_list_filename),
    'transplant_list_filepath': os.path.join(internal_data_basepath, transplant_list_filename),
    'bundled_mother_filepath': os.path.join(internal_data_basepath, bundled_mother_filename),
    'bundled_infant_filepath': os.path.join(internal_data_basepath, bundled_infant_filename),
    'output_filepath': os.path.join(output_data_basepath, output_filename),
    'log_output_filepath': log_output_filepath
}

