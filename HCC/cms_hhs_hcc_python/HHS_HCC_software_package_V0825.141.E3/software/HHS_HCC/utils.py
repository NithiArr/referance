import pandas as pd
import numpy as np
from datetime import datetime
import logging

from common.utils import evaluate_age_rule, cc_to_col, safe_int

def get_enrollee_info_df(enrollee_df: pd.DataFrame) -> pd.DataFrame:
    '''
    Validate and get relevant cols
    '''
    # Verify columns exist as expected
    expected_cols = ['ID', 'SEX', 'DOB', 'AGE_LAST', 'METAL', 'CSR_INDICATOR', 'ENROLDURATION']
    for col in expected_cols:
        if col not in enrollee_df.columns:
            raise ValueError(f"Column {col} is missing from person-level DataFrame")
   
     # Capitalize all METAL values 
    enrollee_df['METAL'] = enrollee_df['METAL'].astype(str).str.upper()
            
    return enrollee_df[expected_cols]

def get_enrollee_age_sex_vars(enrollee_row: pd.Series, age_sex_init_vars: dict, age_ranges: list) -> pd.Series: 
    '''
    For enrollee in enrollee_row, marks applicable age/sex categories in the initialized dict and returns
    enrollee row with age/sex vars added. 
    '''
    enrollee_row_init_vars = age_sex_init_vars.copy()
    age = int(enrollee_row['AGE_LAST'])
    sex = enrollee_row['SEX']
    
    sex_char = 'M' if int(sex) == 1 else 'F' if int(sex) == 2 else None
    if not sex_char:
        raise ValueError(f"Invalid sex value: {sex} for enrollee id {enrollee_row['ID']}")
    
    # Handle special cases for M with age < 2
    if sex_char == 'M' and age in [0, 1]: 
        enrollee_row_init_vars[f'AGE{age}_MALE'] = 1
    
    for start, stop in age_ranges:
        if age >= start and (stop is None or age <= stop):
            stop_suffix = 'GT' if stop is None else stop
            key = f'{sex_char}AGE_LAST_{start}_{stop_suffix}'
            enrollee_row_init_vars[key] = 1
            break
        
    return pd.Series({**enrollee_row, **enrollee_row_init_vars})


def get_enrollee_diagnosis_hhs_cc_df(enrollee_diag_cc_init_df, icd10_mappings, ICD10_is_valid_cols, benefit_year, date_format, age_col: str = "AGE", switch_edits: bool = True): 
    '''
    Set the corresponding column in CCS to 1 if the
    '''
    # Normalize IDs and ICD10s to strings to avoid type mismatch when merging
    enrollee_diag_cc_init_df = enrollee_diag_cc_init_df.copy()
    icd10_mappings = icd10_mappings.copy()

    enrollee_diag_cc_init_df['ID'] = enrollee_diag_cc_init_df['ID'].astype(str).str.strip()
    icd10_mappings['ICD10'] = icd10_mappings['ICD10'].astype(str).str.strip()
    
    merged = (
        enrollee_diag_cc_init_df
        .merge(icd10_mappings, on='ICD10', how='left')
    )
    
    # iterate as dicts so we can use column name keys directly
    for rec in merged.to_dict('records'):
        enrollee_id = rec.get('ID')
        cc_val = rec.get('CC')
        ICD10_val = rec.get('ICD10')
        is_valid_first_fiscal_year = rec.get([col for col in ICD10_is_valid_cols if str(benefit_year) in col][0])
        is_valid_second_fiscal_year = rec.get([col for col in ICD10_is_valid_cols if not str(benefit_year) in col][0])
        
        enrollee_diag_date = datetime.strptime(str(rec.get('DIAGNOSIS_SERVICE_DATE')), date_format).date()
        
        # check diagnosis service date is within the base year 
        if enrollee_diag_date.year != benefit_year: 
            logging.warning(f'Diagnosis date {enrollee_diag_date} for enrollee ID {enrollee_id} is not within benefit year {benefit_year}. Diagnosis will be skipped.')
            continue
        
        # check that ICD10 is valid given the diagnosis_date and cutoff date for benefit vs fiscal year
        fiscal_cutoff_date = datetime(benefit_year, 10, 1).date()
        

        # If diagnosis date is before fiscal year cutoff date, ICD10 must be valid for the first fiscal year within benefit year
        if enrollee_diag_date < fiscal_cutoff_date and is_valid_first_fiscal_year == False:
            logging.warning(
                f'Diagnosis date {enrollee_diag_date} for {enrollee_id} with ICD10 code {ICD10_val} is not within fiscal year {benefit_year}. Diagnosis will be skipped.')
            continue
        # If diagnosis date is on or after the fiscal year cutoff date, ICD10 mut be valid in the second fiscal year within the benefit year
        if enrollee_diag_date >= fiscal_cutoff_date and is_valid_second_fiscal_year == False:
            logging.warning(
                f'Diagnosis date {enrollee_diag_date} for {enrollee_id} with ICD10 code {ICD10_val} is not within fiscal year {benefit_year}. Diagnosis will be skipped.')
            continue
        
        if pd.isna(cc_val) or cc_val is None:
            continue

        cc_col_name = f"HHS_CC{cc_to_col(str(cc_val))}"
        if cc_col_name not in enrollee_diag_cc_init_df.columns:
            continue

        enrollee_age = safe_int(rec.get(age_col))
        enrollee_sex = safe_int(rec.get('SEX'))

        # If switch_edits enabled, only check MCE age edits
        if switch_edits:
            mce_age_cond = rec.get('MCE_AGE_CONDITION')
            if pd.notnull(mce_age_cond):
                # Use bene age at diagnosis for MCE age
                enrollee_diagnosis_age = safe_int(rec.get('AGE_AT_DIAGNOSIS'))
                if enrollee_diagnosis_age is None or not evaluate_age_rule(str(mce_age_cond), enrollee_age):
                    continue

        # age and sex edit checks (applies regardless of switch_edits in your original code)
        age_edit_cond = rec.get('AGE_EDIT_CONDITION')
        if pd.notnull(age_edit_cond):
            if enrollee_age is None or not evaluate_age_rule(str(age_edit_cond), enrollee_age):
                continue
        sex_edit_cond = rec.get('SEX_EDIT_CONDITION')
        if pd.notnull(sex_edit_cond):
            sex_edit_int = safe_int(sex_edit_cond)
            if enrollee_sex is None or sex_edit_int is None or enrollee_sex != sex_edit_int:
                continue

        # set the CC flag for this enrollee ID
        enrollee_diag_cc_init_df.loc[enrollee_diag_cc_init_df['ID'] == enrollee_id, cc_col_name] = 1
    
    CC_cols = [col for col in enrollee_diag_cc_init_df.columns if col.startswith('HHS_CC')]
    return enrollee_diag_cc_init_df.groupby('ID')[CC_cols].max().reset_index()

def format_three(code, width=3):
    '''
    Use to reformat HCC cols with leading zeros
    '''
    s = str(code)
    if '_' in s:
        left, right = s.split('_', 1)     # only split on the first underscore
        left = left.zfill(width)
        return f"{left}_{right}"
    return s.zfill(width)

def create_rxcs(enroll_df, ndc_df, hcpcs_df, ndc_mapping, hcpcs_mapping, RXC_hierarchy):
    #Set maximum RXC value parameter
    MAX_RXC_VALUE = 10

    # Convert enroll_df ID to string to match NDC and HCPCS files
    enroll_df['ID'] = enroll_df['ID'].astype(str)
    ndc_df['ID'] = ndc_df['ID'].astype(str)
    hcpcs_df['ID'] = hcpcs_df['ID'].astype(str)
    ndc_df['NDC'] = ndc_df['NDC'].astype(str)
    hcpcs_df['HCPCS'] = hcpcs_df['HCPCS'].astype(str)
    hcpcs_mapping['HCPCS'] = hcpcs_mapping['HCPCS'].astype(str)
    ndc_mapping['NDC'] = ndc_mapping['NDC'].astype(str)
    ndc_df['NDC'] = ndc_df['NDC'].str.replace(r'\.0$', '', regex=True)
    ndc_df['NDC'] = ndc_df['NDC'].str.zfill(11)
    ndc_mapping['NDC'] = ndc_mapping['NDC'].str.zfill(11)


    # Create enroll_df_adult dataframe by filtering to AGE_LAST >20
    enroll_df_adult = enroll_df[enroll_df['AGE_LAST'] > 20]

    # Merge enroll_df with NDC and HCPCS files
    enroll_ndc_df = enroll_df_adult.merge(ndc_df, on="ID", how="left")
    enroll_hcpcs_df = enroll_df_adult.merge(hcpcs_df, on="ID", how="left")

    # Merge with mapping files
    enroll_ndc_mapped_df = enroll_ndc_df.merge(ndc_mapping, on="NDC", how="left")
    enroll_hcpcs_mapped_df = enroll_hcpcs_df.merge(hcpcs_mapping, on="HCPCS", how="left")

    # Combine both NDC and HCPCS RXCs
    enroll_rxc_long_df = pd.concat([enroll_ndc_mapped_df, enroll_hcpcs_mapped_df], axis=0)

    # Convert RXC to numeric
    enroll_rxc_long_df['RXC'] = pd.to_numeric(enroll_rxc_long_df['RXC'], errors='coerce').astype('Int64')

    # Create dummy variables
    rxc_vars_int_df = pd.get_dummies(enroll_rxc_long_df['RXC'], prefix='RXC')

    # Ensure dummy values are ints
    for col in rxc_vars_int_df.columns:
        rxc_vars_int_df[col] = rxc_vars_int_df[col].astype(int)

    # Add ID back
    rxc_vars_int_df['ID'] = enroll_rxc_long_df['ID'].values

    # Group by ID
    rxc_vars_df = rxc_vars_int_df.groupby('ID').max().reset_index()

    # Create any columns RXC_1 through RXC_10 that are missing and fill with 0s
    for i in range(1, MAX_RXC_VALUE + 1):
        col = f'RXC_{i}'
        if col not in rxc_vars_df.columns:
            rxc_vars_df[col] = 0  # Add missing columns with 0s

    # Reorder columns: ID first, then RXC_1 to RXC_10
    rxc_cols = [f'RXC_{i}' for i in range(1, MAX_RXC_VALUE + 1)]
    rxc_vars_df = rxc_vars_df[['ID'] + rxc_cols]

    # Enforce hierarchy rules
    for _, row in RXC_hierarchy.iterrows():
        if pd.isna(row['Secondary_RXC']):
            continue

        primary_col = f"RXC_{int(row['RXC'])}"
        secondary_col = f"RXC_{int(row['Secondary_RXC'])}"

        if primary_col in rxc_vars_df.columns and secondary_col in rxc_vars_df.columns:
            rxc_vars_df.loc[rxc_vars_df[primary_col] == 1, secondary_col] = 0
    
    #Add leading zeros to RXC column names if RXC is a single digit
    rxc_vars_df.columns = [f"RXC_{int(col.split('_')[1]):02}" if col.startswith("RXC_") else col for col in rxc_vars_df.columns]

    return rxc_vars_df

def create_adult_model_vars(enroll_df, enrollee_age_sex_df, rxc_df, hcc_df, adult_group_mappings_df, severe_list_df, transplant_list_df, rxc_interactions_df, diagnoses_df, bundled_mother):
    # Create adult model variables
    enroll_df['ID'] = enroll_df['ID'].astype(str)
    enroll_df['AGE_LAST'] = enroll_df['AGE_LAST'].astype(int)
    enrollee_age_sex_df['ID'] = enrollee_age_sex_df['ID'].astype(str)
    rxc_df['ID'] = rxc_df['ID'].astype(str)    
    hcc_df['ID'] = hcc_df['ID'].astype(str)
    adult_group_mappings_df['Group'] = adult_group_mappings_df['Group'].astype(str)
    adult_group_mappings_df['HCC_list_1'] = adult_group_mappings_df['HCC_list_1'].astype("string")
    adult_group_mappings_df['HCC_list_2'] = adult_group_mappings_df['HCC_list_2'].astype("string")
    adult_group_mappings_df['HCC_list_3'] = adult_group_mappings_df['HCC_list_3'].astype("string")
    severe_list_df['severe_list'] = severe_list_df['severe_list'].astype(str)
    severe_list_df['adult'] = severe_list_df['adult'].astype(str)
    transplant_list_df['transplant_list'] = transplant_list_df['transplant_list'].astype(str)
    transplant_list_df['adult'] = transplant_list_df['adult'].astype(str)
    rxc_interactions_df['RXC_interaction'] = rxc_interactions_df['RXC_interaction'].astype(str)
    rxc_interactions_df['RXC'] = rxc_interactions_df['RXC'].astype(str)
    rxc_interactions_df['HCC_list_1'] = rxc_interactions_df['HCC_list_1'].astype(str)
    rxc_interactions_df['HCC_list_2'] = rxc_interactions_df['HCC_list_2'].astype(str)
    rxc_interactions_df['HCC_list_3'] = rxc_interactions_df['HCC_list_3'].astype(str)
    rxc_interactions_df['HCC_list_4'] = rxc_interactions_df['HCC_list_4'].astype(str)
    rxc_interactions_df['HCC_list_5'] = rxc_interactions_df['HCC_list_5'].astype(str)

    # Merge enroll_df with rxc_df on ID
    enroll_rxc_df = enroll_df.merge(rxc_df, on="ID", how="left")

    hcc_df = hcc_df.drop_duplicates(subset=["ID"])

    # Merge enroll_rxc_df with hcc_df on ID
    enroll_rxc_hcc_df = enroll_rxc_df.merge(hcc_df, on="ID", how="left")

    # Merge age_sex variables with enroll_rxc_hcc_df on ID
    full_model_df = enroll_rxc_hcc_df.merge(enrollee_age_sex_df, on="ID", how="left")

    # Create adult_model dataframe by filtering to AGE_LAST >20
    adult_model_df = full_model_df[full_model_df['AGE_LAST'] > 20]

    # Make a copy of the dataframe
    adult_model_df = adult_model_df.copy()
    adult_model_df_pre_grouping = adult_model_df.copy()

    # Warn for missing ENROLDURATION (one warning per enrollee/row)
    missing_enrol = adult_model_df[adult_model_df["ENROLDURATION"].isna()]
    
    for _, r in missing_enrol.iterrows():
        logging.warning(
            f'Enrollee {r["ID"]} is missing ENROLDURATION.'
            'This enrollee may be excluded or have incomplete eligibility/enrollment history.'
        )

    # Iterate over each group row in the mappings file
    for _, row in adult_group_mappings_df.iterrows():
        group_name = row['Group']
        # Collect HCCs involved in the group
        hccs = [hcc for hcc in [row['HCC_list_1'], row['HCC_list_2'], row['HCC_list_3']] if pd.notnull(hcc)]
        # Create a new column for the group in adult_model_df, initialize with 0
        adult_model_df[group_name] = (adult_model_df[hccs] == 1).any(axis=1).astype(int)

        # Set the individual HCCs to 0 where the group flag was set to 1
        for hcc in hccs:
            adult_model_df.loc[adult_model_df[group_name] == 1, hcc] = 0

    # Create HCC count
    # Get the list of valid group names from the mappings file
    group_names = adult_group_mappings_df['Group'].dropna().tolist()

    # Select columns that start with 'HHS_HCC' (excluding HHS_HCC022)
    # OR are in the list of valid group names
    hcc_columns = [
        col for col in adult_model_df.columns
        if (col.startswith('HHS_HCC') and col != 'HHS_HCC022') or (col in group_names)
    ]
    # Sum across the selected HCC columns to create HCC_CNT
    adult_model_df['HCC_CNT'] = adult_model_df[hcc_columns].sum(axis=1)
    # Fill NaN values in HCC_CNT with 0
    adult_model_df['HCC_CNT'] = adult_model_df['HCC_CNT'].fillna(0)

    # Filter rows where adult == 'y'
    adult_severe_df = severe_list_df[severe_list_df['adult'] == 'y']

    # Extract list
    severe_hccs = adult_severe_df['severe_list'].tolist()
    
    # Create SEVERE_HCC_COUNT1 to SEVERE_HCC_COUNT10PLUS columns
    for i in range(1, 11):
        col = f'SEVERE_HCC_COUNT{i if i < 10 else "10PLUS"}'
        adult_model_df[col] = 0

    def has_any_hcc(df, hccs):
        valid = [h for h in hccs if h in df.columns]
        if not valid:
            return pd.Series(False, index=df.index)
        return df[valid].eq(1).any(axis=1)

    has_severe = (
    has_any_hcc(adult_model_df_pre_grouping, severe_hccs) |
    has_any_hcc(adult_model_df, severe_hccs)
    )
    
    adult_model_df['SEVERE'] = has_severe
    
    # Set the appropriate SEVERE_HCC_COUNT* flag
    for i in range(1, 11):
        col = f'SEVERE_HCC_COUNT{i if i < 10 else "10PLUS"}'
        if i < 10:
            condition = (adult_model_df['HCC_CNT'] == i) & has_severe
        else:
            condition = (adult_model_df['HCC_CNT'] >= 10) & has_severe
        adult_model_df.loc[condition, col] = 1

    # Create transplant interactions
    # Filter rows where child == 'y'
    adult_transplant_df = transplant_list_df[transplant_list_df['adult'] == 'y']

    # Extract transplant HCCs list from transplant_list
    transplant_hccs = adult_transplant_df['transplant_list'].tolist()

    # Initialize all TRANSPLANT_HCC_COUNT* columns to 0
    for i in range(4, 9):
        col = f'TRANSPLANT_HCC_COUNT{i if i < 8 else "8PLUS"}'
        adult_model_df[col] = 0

    has_transplant = (
        has_any_hcc(adult_model_df_pre_grouping, transplant_hccs)
        |
        has_any_hcc(adult_model_df, transplant_hccs)
    )
    
    adult_model_df['TRANSPLANT'] = has_transplant

    # Set the appropriate TRANSPLANT_HCC_COUNT* flag
    for i in range(4, 9):
        col = f'TRANSPLANT_HCC_COUNT{i if i < 8 else "8PLUS"}'
        if i < 8:
            condition = (adult_model_df['HCC_CNT'] == i) & has_transplant
        else:
            condition = (adult_model_df['HCC_CNT'] >= 8) & has_transplant
        adult_model_df.loc[condition, col] = 1

    # Create enrollment duration flags
    # Create and initialize HCC_ED1 to HCC_ED6 to 0
    for i in range(1, 7):
        adult_model_df[f'HCC_ED{i}'] = 0

    # Apply the logic where HCC_CNT > 0
    for i in range(1, 7):
        condition = (adult_model_df['HCC_CNT'] > 0) & (adult_model_df['ENROLDURATION'] == i)
        adult_model_df.loc[condition, f'HCC_ED{i}'] = 1

    # Create RXC interactions 
    # Loop through each interaction in rxc_interactions
    for _, row in rxc_interactions_df.iterrows():

        interaction_col = row['RXC_interaction']
        rxc_col = row['RXC']

        # Normalize & validate
        if rxc_col not in adult_model_df.columns:
            continue

        hcc_cols = [
            row[f'HCC_list_{i}']
            for i in range(1, 6)
            if pd.notna(row[f'HCC_list_{i}'])
        ]

        # Initialize interaction column once
        if interaction_col not in adult_model_df.columns:
            adult_model_df[interaction_col] = 0

        # Build condition safely
        condition = (
            (adult_model_df[rxc_col] == 1) &
            (
                has_any_hcc(adult_model_df, hcc_cols)
                |
                has_any_hcc(adult_model_df_pre_grouping, hcc_cols)
            )
        )

        adult_model_df.loc[condition, interaction_col] = 1

    
    adult_model_df['RXC_09_X_HCC056_057_AND_048_041'] = (
        (adult_model_df['RXC_09'] == 1) &
        ((adult_model_df['HHS_HCC056'] == 1) | (adult_model_df['HHS_HCC057'] == 1)) &
        ((adult_model_df['HHS_HCC048'] == 1) | (adult_model_df['HHS_HCC041'] == 1))
    ).astype(int)

    # Restrict diagnoses to IDs present in adult_model_df
    adult_ids = set(
        adult_model_df["ID"]
            .dropna()
            .astype(str)
            .str.strip()
    )
    
    dx_df = diagnoses_df.copy()
    dx_df["ID_clean"] = dx_df["ID"].dropna().astype(str).str.strip()
    
    dx_df = dx_df[dx_df["ID_clean"].isin(adult_ids)].copy()
    
    # Build bundled mother ICD10 set
    bundled_mother_icd10_set = set(
        bundled_mother["ICD10_codes"]
            .dropna()
            .astype(str)
            .str.strip()
            .str.upper()
    )
    
    # Clean DIAG and flag
    dx_df["DIAG_clean"] = (
        dx_df["ICD10"]
            .astype(str)
            .str.strip()
            .str.upper()
    )
    
    flagged = dx_df[dx_df["DIAG_clean"].isin(bundled_mother_icd10_set)]
    
    # Log warnings
    for _, r in flagged.iterrows():
        logging.warning(
            f'Enrollee {r["ID"]} has diagnosis code {r["DIAG_clean"]}, which is flagged as a bundled mother/infant code. '
            'This enrollee may have bundled mother/infant claims.'
        )

    return adult_model_df

def create_child_model_vars(enroll_df, enrollee_age_sex_df, hcc_df, child_group_mappings_df, severe_list_df, transplant_list_df, diagnoses_df, bundled_mother):
    #Create child model variables
    enroll_df['ID'] = enroll_df['ID'].astype(str)
    enroll_df['AGE_LAST'] = enroll_df['AGE_LAST'].astype(int)
    hcc_df['ID'] = hcc_df['ID'].astype(str)
    enrollee_age_sex_df['ID'] = enrollee_age_sex_df['ID'].astype(str)
    child_group_mappings_df['Group'] = child_group_mappings_df['Group'].astype(str)
    child_group_mappings_df['HCC_list_1'] = child_group_mappings_df['HCC_list_1'].astype("string")
    child_group_mappings_df['HCC_list_2'] = child_group_mappings_df['HCC_list_2'].astype("string")
    child_group_mappings_df['HCC_list_3'] = child_group_mappings_df['HCC_list_3'].astype("string")
    severe_list_df['severe_list'] = severe_list_df['severe_list'].astype(str)
    severe_list_df['child'] = severe_list_df['child'].astype(str)
    transplant_list_df['transplant_list'] = transplant_list_df['transplant_list'].astype(str)
    transplant_list_df['child'] = transplant_list_df['child'].astype(str)

    hcc_df = hcc_df.drop_duplicates(subset=["ID"])

    # Merge enroll_df with hcc_df on ID
    enroll_hcc_df = enroll_df.merge(hcc_df, on="ID", how="left")

    # Merge age_sex variables with enroll_hcc_df on ID
    full_model_df = enroll_hcc_df.merge(enrollee_age_sex_df, on="ID", how="left")

    # Create child_model dataframe by filtering to AGE_LAST < 21 and > 1
    child_model_df = full_model_df[(full_model_df['AGE_LAST'] < 21) & (full_model_df['AGE_LAST'] > 1)]

    # Make a copy of the dataframe
    child_model_df = child_model_df.copy()
    child_model_df_pre_grouping = child_model_df.copy()

    # Warn for missing ENROLDURATION (one warning per enrollee/row)
    missing_enrol = child_model_df[child_model_df["ENROLDURATION"].isna()]
    
    for _, r in missing_enrol.iterrows():
        logging.warning(
            f'Enrollee {r["ID"]} is missing ENROLDURATION.'
            'This enrollee may be excluded or have incomplete eligibility/enrollment history.'
        )

    # Iterate over each group row in the mappings file
    for _, row in child_group_mappings_df.iterrows():
        group_name = row['Group']
        
        # Collect HCCs involved in the group
        hccs = [hcc for hcc in [row['HCC_list_1'], row['HCC_list_2'], row['HCC_list_3']] if pd.notnull(hcc)]

        # Create a new column for the group in child_model_df, initialize with 0
        child_model_df[group_name] = (child_model_df[hccs] == 1).any(axis=1).astype(int)

        # Set the individual HCCs to 0 where the group flag was set to 1
        for hcc in hccs:
            child_model_df.loc[child_model_df[group_name] == 1, hcc] = 0

    # Create HCC count
    # Get the list of valid group names from the mappings file
    group_names = child_group_mappings_df['Group'].dropna().tolist()

    # Select columns that start with 'HHS_HCC' (excluding HHS_HCC022)
    # OR are in the list of valid group names
    hcc_columns = [
        col for col in child_model_df.columns
        if (col.startswith('HHS_HCC') and col != 'HHS_HCC022') or (col in group_names)
    ]
    # Sum across the selected HCC columns to create HCC_CNT
    child_model_df['HCC_CNT'] = child_model_df[hcc_columns].sum(axis=1)
    # Fill NaN values in HCC_CNT with 0
    child_model_df['HCC_CNT'] = child_model_df['HCC_CNT'].fillna(0)

    # Filter rows where child == 'y'
    child_severe_df = severe_list_df[severe_list_df['child'] == 'y']

    # Extract list
    severe_hccs = child_severe_df['severe_list'].tolist()

    # Create SEVERE_HCC_COUNT1 to SEVERE_HCC_COUNT8PLUS columns
    for i in range(1, 9):
        col = f"SEVERE_HCC_COUNT{i if i < 6 else '6_7' if i in (6, 7) else '8PLUS'}"
        child_model_df[col] = 0

    def has_any_hcc(df, hccs):
        valid = [h for h in hccs if h in df.columns]
        if not valid:
            return pd.Series(False, index=df.index)
        return df[valid].eq(1).any(axis=1)

    has_severe = (
    has_any_hcc(child_model_df_pre_grouping, severe_hccs) |
    has_any_hcc(child_model_df, severe_hccs)
    )
    
    child_model_df['SEVERE'] = has_severe

    # Set the appropriate SEVERE_HCC_COUNT* flag
    for i in range(1, 9):
        col = f"SEVERE_HCC_COUNT{i if i < 6 else '6_7' if i in (6, 7) else '8PLUS'}"
        if i < 8:
            condition = (child_model_df['HCC_CNT'] == i) & has_severe
        else:
            condition = (child_model_df['HCC_CNT'] >= 8) & has_severe
        child_model_df.loc[condition, col] = 1

    # Create transplant interactions
    # Filter rows where child == 'y'
    child_transplant_df = transplant_list_df[transplant_list_df['child'] == 'y']

    # Extract transplant HCCs list from transplant_list
    transplant_hccs = child_transplant_df['transplant_list'].tolist()

    # Initialize TRANSPLANT_HCC_COUNT4PLUS column to 0
    child_model_df['TRANSPLANT_HCC_COUNT4PLUS'] = 0

    has_transplant = (
        has_any_hcc(child_model_df_pre_grouping, transplant_hccs)
        |
        has_any_hcc(child_model_df, transplant_hccs)
    )
    
    child_model_df['TRANSPLANT'] = has_transplant

    # Set the appropriate TRANSPLANT_HCC_COUNT* flag
    condition = (child_model_df['HCC_CNT'] >= 4) & has_transplant
    child_model_df.loc[condition, 'TRANSPLANT_HCC_COUNT4PLUS'] = 1

    # Restrict diagnoses to IDs present in child_model_df
    child_ids = set(
        child_model_df["ID"]
            .dropna()
            .astype(str)
            .str.strip()
    )
    
    dx_df = diagnoses_df.copy()
    dx_df["ID_clean"] = dx_df["ID"].dropna().astype(str).str.strip()
    
    dx_df = dx_df[dx_df["ID_clean"].isin(child_ids)].copy()
    
    # Build bundled mother ICD10 set
    bundled_mother_icd10_set = set(
        bundled_mother["ICD10_codes"]
            .dropna()
            .astype(str)
            .str.strip()
            .str.upper()
    )
    
    # Clean DIAG and flag
    dx_df["DIAG_clean"] = (
        dx_df["ICD10"]
            .astype(str)
            .str.strip()
            .str.upper()
    )
    
    flagged = dx_df[dx_df["DIAG_clean"].isin(bundled_mother_icd10_set)]
    
    # Log warnings
    for _, r in flagged.iterrows():
        logging.warning(
            f'Enrollee {r["ID"]} has diagnosis code {r["DIAG_clean"]}, which is flagged as a bundled mother/infant code. '
            'This enrollee may have bundled mother/infant claims.'
        )
        
    return child_model_df

def create_infant_model_vars(enroll_df, enrollee_age_sex_df, hcc_df, infant_maturity_mappings_df, infant_severity_mappings_df, diagnoses_df, bundled_infant):
    #Create infant model variables
    enroll_df['ID'] = enroll_df['ID'].astype(str)
#    enroll_df['AGE_LAST'] = enroll_df['AGE_LAST'].astype(int)
    enrollee_age_sex_df['ID'] = enrollee_age_sex_df['ID'].astype(str)
    hcc_df['ID'] = hcc_df['ID'].astype(str)
    infant_maturity_mappings_df['maturity_category'] = infant_maturity_mappings_df['maturity_category'].astype(str)
    infant_maturity_mappings_df['HCC_list'] = infant_maturity_mappings_df['HCC_list'].astype(str)
    infant_severity_mappings_df['severity_category'] = infant_severity_mappings_df['severity_category'].astype(str)
    infant_severity_mappings_df['HCC_list'] = infant_severity_mappings_df['HCC_list'].astype(str)

    hcc_df = hcc_df.drop_duplicates(subset=["ID"])

    # Merge enroll_df with hcc_df on ID
    enroll_hcc_df = enroll_df.merge(hcc_df, on="ID", how="left")

    # Merge age_sex variables with enroll_hcc_df on ID
    full_model_df = enroll_hcc_df.merge(enrollee_age_sex_df, on="ID", how="left")

    # Create infant_model dataframe by filtering to AGE_LAST < 2
    infant_model_df = full_model_df[(full_model_df['AGE_LAST'] < 2)]

    # Make a copy of the dataframe
    infant_model_df = infant_model_df.copy()

    # Warn for missing ENROLDURATION (one warning per enrollee/row)
    missing_enrol = infant_model_df[infant_model_df["ENROLDURATION"].isna()]
    
    for _, r in missing_enrol.iterrows():
        logging.warning(
            f'Enrollee {r["ID"]} is missing ENROLDURATION.'
            'This enrollee may be excluded or have incomplete eligibility/enrollment history.'
        )

    # Define severity columns (ordered lowest → highest)
    severity_cols = [f'IHCC_SEVERITY{i}' for i in range(1, 6)]

    # Initialize all severity columns to 0
    infant_model_df.loc[:, severity_cols] = 0

    # Build mapping: severity → list of HCCs
    mapping = (
        infant_severity_mappings_df
        .groupby('severity_category')['HCC_list']
        .apply(list)
        .to_dict()
    )

    # Set severity flags if any mapped HCC == 1
    for sev, hcc_list in mapping.items():
        valid_hccs = [hcc for hcc in hcc_list if hcc in infant_model_df.columns]
        if valid_hccs:
            infant_model_df[sev] = (
                infant_model_df[valid_hccs]
                .eq(1)
                .any(axis=1)
                .astype(int)
            )

    # Create weights so higher severity wins
    weights = np.arange(1, len(severity_cols) + 1)

    # Compute highest severity per row
    weighted = infant_model_df[severity_cols].mul(weights)
    max_severity = weighted.idxmax(axis=1)

    # Detect rows with no severity flagged
    has_any = infant_model_df[severity_cols].any(axis=1)

    # Reset all severity flags
    infant_model_df.loc[:, severity_cols] = 0

    # Assign highest severity
    for col in severity_cols:
        infant_model_df.loc[max_severity == col, col] = 1

    # Default to SEVERITY1 if nothing flagged
    infant_model_df.loc[~has_any, 'IHCC_SEVERITY1'] = 1

    # Create variable IHCC_AGE1 and set = to 1 for enrollees where AGE_LAST = 1, otherwise, set = 0.
    infant_model_df['IHCC_AGE1'] = (infant_model_df['AGE_LAST'] == 1).astype(int)

    # Create variable IHCC_Maturity based on mappings
    # Define the four infant maturity columns
    maturity_cols = [
        'IHCC_EXTREMELY_IMMATURE',
        'IHCC_IMMATURE',
        'IHCC_PREMATURE_MULTIPLES',
        'IHCC_TERM'
    ]

    # Initialize columns to 0
    for col in maturity_cols:
        infant_model_df[col] = 0

    # Group mapping by maturity category to list of HCCs
    mapping = (
        infant_maturity_mappings_df
        .groupby('maturity_category')['HCC_list']
        .apply(list)
        .to_dict()
    )

    # Subset for infants (AGE_LAST < 1)
    infants_lt1_subset = infant_model_df['AGE_LAST'] < 1

    # Apply mapping for each maturity category
    for maturity, hcc_list in mapping.items():
        # Ensure only valid HCC columns present in the dataframe
        valid_hccs = [hcc for hcc in hcc_list if hcc in infant_model_df.columns]
        if not valid_hccs:
            continue

        # Create boolean condition: infant has any of those HCCs == 1
        has_hcc = (infant_model_df[valid_hccs].eq(1)).any(axis=1)

        # Apply only when AGE_LAST < 1
        infant_model_df.loc[infants_lt1_subset & has_hcc, maturity] = 1
    
    hcc_cols = infant_maturity_mappings_df['HCC_list'].unique().tolist()

    # Create subset for "none of the HCCs == 1"
    no_hccs = ~infant_model_df[hcc_cols].eq(1).any(axis=1)

    # Set IHCC_AGE1 = 1 where both conditions are met
    infant_model_df.loc[infants_lt1_subset & no_hccs, 'IHCC_AGE1'] = 1

    # Define hierarchy (highest first)
    maturity_hierarchy = [
        'IHCC_EXTREMELY_IMMATURE',
        'IHCC_IMMATURE',
        'IHCC_PREMATURE_MULTIPLES',
        'IHCC_TERM',
        'IHCC_AGE1',
    ]

    # Keep only columns that exist
    present_cols = [c for c in maturity_hierarchy if c in infant_model_df.columns]

    if present_cols:
        # Get a boolean dataframe of the maturity cols
        m = infant_model_df[present_cols].to_numpy(dtype=bool)

        # Determine first True in each row according to hierarchy
        first_true_idx = m.argmax(axis=1)

        # If a row contains no True values, argmax returns 0, but all are False.
        # We detect those and invalidate.
        has_any = m.any(axis=1)
        first_true_idx[~has_any] = -1   # sentinel for "no category"

        # Zero-out all maturity columns
        infant_model_df.loc[:, present_cols] = 0

        # Set exactly one column to 1 per row (where applicable)
        for i, col in enumerate(present_cols):
            mask = first_true_idx == i
            infant_model_df.loc[mask, col] = 1

    # Map interaction label to existing maturity column
    maturity_map = {
        'EXTREMELY_IMMATURE': 'IHCC_EXTREMELY_IMMATURE',
        'IMMATURE': 'IHCC_IMMATURE',
        'PREMATURE_MULTIPLES': 'IHCC_PREMATURE_MULTIPLES',
        'TERM': 'IHCC_TERM',
        'AGE1': 'IHCC_AGE1', 
    }

    # Confirm which severity columns exist
    severity_cols = [f'IHCC_SEVERITY{i}' for i in range(1, 6) if f'IHCC_SEVERITY{i}' in infant_model_df.columns]

    # Loop through each severity × maturity combination
    for sev in severity_cols:
        sev_num = sev.split('IHCC_SEVERITY')[-1]  # extracts suffix, e.g., '_1'
        sev_flag = infant_model_df[sev].fillna(0).astype(int)

        for label, mcol in maturity_map.items():
            m_flag = infant_model_df[mcol].fillna(0).astype(int)
            out_col = f'{label}_X_SEVERITY{sev_num}'
            infant_model_df[out_col] = (m_flag * sev_flag).astype(int)

    #Check that no enrollee has more than one severity x maturity flag
    interaction_cols = [f'{label}_X_SEVERITY{sev_num}' 
                        for sev_num in range(1, 6) 
                        for label in maturity_map.keys()
                        if f'{label}_X_SEVERITY{sev_num}' in infant_model_df.columns]
    interaction_sum = infant_model_df[interaction_cols].sum(axis=1)
    if not (interaction_sum <= 1).all():
        raise ValueError("An enrollee has more than one severity x maturity flag set to 1.")

    # Restrict diagnoses to IDs present in infant_model_df
    infant_ids = set(
        infant_model_df["ID"]
            .dropna()
            .astype(str)
            .str.strip()
    )
    
    dx_df = diagnoses_df.copy()
    dx_df["ID_clean"] = dx_df["ID"].dropna().astype(str).str.strip()
    
    dx_df = dx_df[dx_df["ID_clean"].isin(infant_ids)].copy()
    
    # Build bundled infant ICD10 set
    bundled_infant_icd10_set = set(
        bundled_infant["ICD10_codes"]
            .dropna()
            .astype(str)
            .str.strip()
            .str.upper()
    )
    
    # Clean DIAG and flag
    dx_df["DIAG_clean"] = (
        dx_df["ICD10"]
            .astype(str)
            .str.strip()
            .str.upper()
    )
    
    flagged = dx_df[dx_df["DIAG_clean"].isin(bundled_infant_icd10_set)]
    
    # Log warnings
    for _, r in flagged.iterrows():
        logging.warning(
            f'Enrollee {r["ID"]} has diagnosis code {r["DIAG_clean"]}, which is flagged as a bundled mother/infant code. '
            'This enrollee may have bundled mother/infant claims.'
        )
    
    return infant_model_df

def create_score_tables(model_df, factors_df, csr_table, model_name):

    create_scores_df = model_df.copy()

    PLAN_COLS = [
    "Platinum Level",
    "Gold Level",
    "Silver Level",
    "Bronze Level",
    "Catastrophic Level",
    ]

    # Coerce CSR_INDICATOR to numeric
    create_scores_df = create_scores_df.reset_index(drop=True)

    create_scores_df["CSR_INDICATOR"] = pd.to_numeric(create_scores_df["CSR_INDICATOR"], errors="coerce")
    if create_scores_df["CSR_INDICATOR"].isna().any():
        raise ValueError(
            f"CSR_INDICATOR contains non-numeric or missing values in model '{model_name}'."
        )
    
    #DELETE after testing
    scores_df = create_scores_df.copy()

    csr_table = csr_table.drop_duplicates(subset="RA_CSR_Indicator")
    # Map CSR_INDICATOR to RA_FACTOR
    ra_map = csr_table.set_index("RA_CSR_Indicator")["RA_Factor"]

    # force numeric RA_Factor
    ra_map = pd.to_numeric(ra_map, errors="coerce")

    if ra_map.isna().any():
        raise ValueError(
            f"CSR_table contains non-numeric RA_Factor values."
        )

    create_scores_df["RA_FACTOR"] = create_scores_df["CSR_INDICATOR"].map(ra_map)

    missing_ra = create_scores_df.loc[create_scores_df["RA_FACTOR"].isna(), "CSR_INDICATOR"].unique()
    if len(missing_ra) > 0:
        raise ValueError(
            f"CSR_INDICATOR values {sorted(missing_ra.tolist())} in model '{model_name}' "
            f"do not have matching RA_Factor entries."
        )

    create_scores_df["RA_FACTOR"] = create_scores_df["RA_FACTOR"].astype(float)

    # Variable alignment protections
    if "Variable" not in factors_df.columns:
        raise ValueError(f"factors_df for '{model_name}' must contain 'Variable'.")

    factor_vars = list(factors_df["Variable"])

    # Check variables exist
    missing_in_model = [v for v in factor_vars if v not in create_scores_df.columns]
    if missing_in_model:
        raise ValueError(
            f"Variables {missing_in_model} from factors_df are missing in model_df for '{model_name}'."
        )

    indicator_cols = factor_vars  # need to use exactly the factor variables

    # Coerce indicator columns to numeric
    for col in indicator_cols:
        create_scores_df[col] = pd.to_numeric(create_scores_df[col], errors="coerce").fillna(0)

    # Validate coefficient columns
    missing_plan_cols = [c for c in PLAN_COLS if c not in factors_df.columns]
    if missing_plan_cols:
        raise ValueError(
            f"Missing plan columns {missing_plan_cols} in factors_df for '{model_name}'."
        )

    factors = factors_df.set_index("Variable")[PLAN_COLS].loc[indicator_cols]

    # coerce coefficients to float and check validity
    for plan_col in PLAN_COLS:
        factors[plan_col] = pd.to_numeric(factors[plan_col], errors="coerce")
        if factors[plan_col].isna().any():
            bad = factors.index[factors[plan_col].isna()].tolist()
            raise ValueError(
                f"Non-numeric or missing coefficients in column '{plan_col}' "
                f"for model '{model_name}' for variables: {bad}"
            )

    factors = factors.astype(float)

    # Compute base score columns
    new_cols = {}

    for plan_col in PLAN_COLS:
        coeffs = factors[plan_col]
        score_series = create_scores_df[indicator_cols].dot(coeffs)

        plan_suffix = plan_col.replace(" Level", "").upper()
        score_col = f"SCORE_{model_name}_{plan_suffix}"

        new_cols[score_col] = score_series.astype(float)

    # Add all columns at once
    create_scores_df = pd.concat(
        [create_scores_df, pd.DataFrame(new_cols)],
        axis=1
    )

    score_cols = list(new_cols.keys())

    # Define SCORE columns based on model_name
    platinum_col     = f"SCORE_{model_name}_PLATINUM"
    gold_col         = f"SCORE_{model_name}_GOLD"
    silver_col       = f"SCORE_{model_name}_SILVER"
    bronze_col       = f"SCORE_{model_name}_BRONZE"
    catastrophic_col = f"SCORE_{model_name}_CATASTROPHIC"


    # Define METAL conditions
    conditions = [
        create_scores_df["METAL"] == "P",
        create_scores_df["METAL"] == "G",
        create_scores_df["METAL"] == "S",
        create_scores_df["METAL"] == "B",
        create_scores_df["METAL"] == "C",
    ]

    choices = [
        create_scores_df[platinum_col],
        create_scores_df[gold_col],
        create_scores_df[silver_col],
        create_scores_df[bronze_col],
        create_scores_df[catastrophic_col],
    ]

    total_col = f"SCORE_{model_name}"
    result = np.select(conditions, choices, default=np.nan)
    create_scores_df[total_col] = result 

    # Build CSR-adjusted component score columns
    csr_score_cols = []
    metal_codes = ["P", "G", "S", "B", "C"]  # aligned with PLAN_COLS / score_cols

    new_cols = {}
    for plan_col, metal_code in zip(score_cols, metal_codes):
        mask = create_scores_df["METAL"] == metal_code
        # compute adjusted column as a Series (single object per loop, not inserted yet)
        new_cols[f"CSR_ADJUSTED_{plan_col}"] = (create_scores_df[plan_col].astype(float)
                                            .where(~mask, create_scores_df["RA_FACTOR"] * create_scores_df[plan_col].astype(float)))
    # assign all new columns in one operation
    create_scores_df = create_scores_df.assign(**new_cols)
    csr_score_cols = list(new_cols.keys())

    # Define CSR-adjusted SCORE columns
    csr_platinum_col     = f"CSR_ADJUSTED_SCORE_{model_name}_PLATINUM"
    csr_gold_col         = f"CSR_ADJUSTED_SCORE_{model_name}_GOLD"
    csr_silver_col       = f"CSR_ADJUSTED_SCORE_{model_name}_SILVER"
    csr_bronze_col       = f"CSR_ADJUSTED_SCORE_{model_name}_BRONZE"
    csr_catastrophic_col = f"CSR_ADJUSTED_SCORE_{model_name}_CATASTROPHIC"

    csr_choices = [
        create_scores_df[csr_platinum_col],
        create_scores_df[csr_gold_col],
        create_scores_df[csr_silver_col],
        create_scores_df[csr_bronze_col],
        create_scores_df[csr_catastrophic_col],
    ]

    # Assign CSR_ADJUSTED_SCORE_{model_name}
    total_csr_col = f"CSR_ADJUSTED_SCORE_{model_name}"
    create_scores_df[total_csr_col] = np.select(conditions, csr_choices, default=np.nan)

    # Final output
    create_scores_df[score_cols] = create_scores_df[score_cols].round(3)
    create_scores_df[csr_score_cols] = create_scores_df[csr_score_cols].round(3)

    scores_df = create_scores_df[
        ["ID"] +
        score_cols +
        [total_col] +
        csr_score_cols +
        [total_csr_col]
    ]

    return scores_df
