import logging
import pandas as pd
import os
import sys 
from datetime import datetime

software_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..', 'software'))
if software_path not in sys.path:
    sys.path.insert(0, software_path)

from HHS_HCC.config import main_filepaths, run_spec
from HHS_HCC.utils import *
from common.utils import calculate_age, map_ccs_to_hccs, cc_to_col

'''
Purpose: 
    Calculate risk scores for input enrollees. 
Requires:
    configured run_spec variable in ./software/HHS_HCC/config.py with preferred switch settings
    the following user-defined files saved in ./software/HHS_HCC/data/input/user_defined/ and 
    configured per the readme.md instruction file:
    - person-level file saved as 'PERSON.csv'
    - diagnosis file saved as 'DIAGNOSES.csv'
    - national drug code file saved as 'NDC.csv'
    - healthcare common procedure coding system file saved as 'HCPCS.csv'
Returns:
    person-level scores saved in ./software/HHS_HCC/data/output
    log saved in ./software/HHS_HCC/logs
'''

def transform_hhs_hcc_scores(run_spec, filepaths): 
    """
    Generate enrollee HCC data and risk scores

    Parameters:
    - run_spec: Dictionary containing run specifications, imported from config.py
    - filepaths: Dictionary containing file paths for input and output files, imported from config.py
    """
    logging.basicConfig(filename=filepaths['log_output_filepath'], filemode='w', level=logging.DEBUG)

    try: 
        logging.info('Loading data')
        enrollee_df = pd.read_csv(filepaths['enrollee_filepath'], dtype={"ID": str})
        diagnoses_df = pd.read_csv(filepaths['diagnoses_filepath'], dtype={"ID": str})
        hcpcs_df = pd.read_csv(filepaths['hcpcs_filepath'], dtype={"ID": str})
        ndc_df = pd.read_csv(filepaths['ndc_filepath'], dtype={"ID": str})
        
        # Load internal input data
        CSR_table = pd.read_csv(filepaths['csr_table_filepath'])
        HCC_hierarchy = pd.read_csv(filepaths['hcc_hierarchy_filepath'])
        HCPCS_mappings = pd.read_csv(filepaths['HCPCS_mappings_filepath'], low_memory=False)
        ICD10_mappings = pd.read_csv(filepaths['ICD10_mappings_filepath'], low_memory=False)
        NDC_mappings = pd.read_csv(filepaths['NDC_mappings_filepath'], low_memory=False)
        RXC_hierarchy = pd.read_csv(filepaths['RXC_hierarchy_filepath'])
        RXC_interactions = pd.read_csv(filepaths['RXC_interactions_filepath'])
        adult_factors = pd.read_csv(filepaths['adult_factors_filepath'])
        adult_group_mappings = pd.read_csv(filepaths['adult_group_mappings_filepath'])
        child_factors = pd.read_csv(filepaths['child_factors_filepath'])
        child_group_mappings = pd.read_csv(filepaths['child_group_mappings_filepath'])
        infant_factors = pd.read_csv(filepaths['infant_factors_filepath'])
        infant_maturity_mappings = pd.read_csv(filepaths['infant_maturity_mappings_filepath'])
        infant_severity_mappings = pd.read_csv(filepaths['infant_severity_mappings_filepath'])
        severe_list = pd.read_csv(filepaths['severe_list_filepath'])
        transplant_list = pd.read_csv(filepaths['transplant_list_filepath'])
        bundled_mother = pd.read_csv(filepaths['bundled_mother_filepath'])
        bundled_infant = pd.read_csv(filepaths['bundled_infant_filepath'])
        
        logging.info('Creating enrollee info table')
        enrollee_info_df = get_enrollee_info_df(enrollee_df)
        
        logging.info('Creating age/sex variables')
        # Define inclusive age ranges
        age_ranges = [(0,0), (1,1), (2, 4), (5, 9), (10, 14), (15, 20), (21, 24), 
                      (25, 29), (30, 34), (35, 39), (40, 44), (45, 49), (50, 54), 
                      (55, 59), (60, None)
        ]
        
        # Initialize list with special case for Males < 2
        age_sex_init_vars = {"AGE0_MALE": 0, "AGE1_MALE": 0}
        # Initialize remaining vars
        for start, stop in age_ranges: 
            for sex_char in ['M', 'F']:
                var_name = f'{sex_char}AGE_LAST_{start}_{stop if stop is not None else "GT"}'
                age_sex_init_vars[var_name] = 0
        demographic_age_sex_col_names = list(age_sex_init_vars.keys())
        enrollee_age_sex_df = enrollee_info_df.apply(get_enrollee_age_sex_vars, axis=1, args=(age_sex_init_vars, age_ranges))
 
        logging.info('Assigning CCs from diagnoses and age/sex criteria')        
        # Join enrollee info and diagnosis df
        enrollee_age_sex_diag_df = enrollee_age_sex_df.merge(diagnoses_df, on='ID', how='left')
        # Get age at diagnosis for MCE age edits
        enrollee_age_sex_diag_df['AGE_AT_DIAGNOSIS'] = enrollee_age_sex_diag_df.apply(
            lambda enrollee_row: calculate_age(
                datetime.strptime(str(enrollee_row['DOB']), run_spec['date_format']), 
                datetime.strptime(str(enrollee_row['DIAGNOSIS_SERVICE_DATE']), run_spec['date_format'])
                ), 
            axis=1 
        )
                
        # Initialize enrollee cc df
        hcc_prefix = "HHS_HCC"
        cc_list = HCC_hierarchy['HHS_HCC'].unique().tolist()
        cc_id_list = [cc[len(hcc_prefix):] if cc.startswith(hcc_prefix) else cc for cc in cc_list]
        hcc_col_names = [f"HHS_CC{cc_to_col(cc_id)}" for cc_id in cc_id_list]
        enrollee_cc_init_df = enrollee_age_sex_diag_df.copy()
        zeros = pd.DataFrame(0,
                             index=enrollee_cc_init_df.index,
                             columns=hcc_col_names)


        enrollee_cc_init_df = pd.concat([enrollee_cc_init_df, zeros], axis=1)
        
        # Get diagnosis CCs using AGE_LAST for age edits
        enrollee_diagnosis_cc_df = get_enrollee_diagnosis_hhs_cc_df(enrollee_cc_init_df, ICD10_mappings, run_spec['ICD10_is_valid_cols'], run_spec['benefit_year'], \
            run_spec['date_format'], age_col='AGE_LAST', switch_edits=run_spec['switch_edits'])
        
        cc_col_names = [
            col for col in enrollee_diagnosis_cc_df.columns if col.startswith('HHS_CC')]
        enrollee_diagnosis_cc_df = enrollee_diagnosis_cc_df[['ID'] + cc_col_names]
        
        logging.info('Applying CC hierarchies')
        # reformat HCCs
        for col in HCC_hierarchy.columns:
            HCC_hierarchy[col] = HCC_hierarchy[col].apply(
                lambda hcc: cc_to_col(hcc[len(hcc_prefix):]) if isinstance(hcc, str) and hcc.startswith(hcc_prefix) else hcc
            )
        enrollee_hcc_df = map_ccs_to_hccs(enrollee_diagnosis_cc_df, HCC_hierarchy, hcc_prefix="HHS_")
        # fix col names to match proceeding zeros 
        enrollee_hcc_df = enrollee_hcc_df.rename(
            columns={
                col: f"{hcc_prefix}{format_three(col.replace(hcc_prefix, ''))}"
                for col in enrollee_hcc_df.columns
                if col.startswith(hcc_prefix)
            }
        )
        logging.info('Creating RXC variables')
        rxc_vars_df = create_rxcs(enrollee_info_df, ndc_df, hcpcs_df, NDC_mappings, HCPCS_mappings, RXC_hierarchy)
        
        # remodel age/sex df to include only newly created cols
        common_cols = [col for col in enrollee_info_df.columns.tolist() if col != 'ID']
        enrollee_age_sex_df = enrollee_age_sex_df[enrollee_age_sex_df.columns.difference(common_cols)].copy()
        
        logging.info('Creating adult model variables')
        adult_model_vars_df = create_adult_model_vars(
            enrollee_info_df, enrollee_age_sex_df, rxc_vars_df, enrollee_hcc_df, adult_group_mappings, severe_list, transplant_list, RXC_interactions, diagnoses_df, bundled_mother
        )
        
        logging.info('Creating child model variables')
        child_model_vars_df = create_child_model_vars(
            enrollee_info_df, enrollee_age_sex_df, enrollee_hcc_df, child_group_mappings, severe_list, transplant_list, diagnoses_df, bundled_mother
        )
        
        logging.info('Creating infant model variables')
        infant_model_vars_df = create_infant_model_vars(
            enrollee_info_df, enrollee_age_sex_df, enrollee_hcc_df, infant_maturity_mappings, infant_severity_mappings, diagnoses_df, bundled_infant
        )
        
        logging.info('Creating adult score table')
        adult_scores_df = create_score_tables(
            adult_model_vars_df,
            adult_factors,
            CSR_table,
            "ADULT"
        )

        logging.info('Creating child score table')
        child_scores_df = create_score_tables(
            child_model_vars_df,
            child_factors,
            CSR_table,
            "CHILD"
        )

        logging.info('Creating infant score table')
        infant_scores_df = create_score_tables(
            infant_model_vars_df,
            infant_factors,
            CSR_table,
            "INFANT"
        )
        
        # Merge all scores
        logging.info('Merging all score tables') 
        adult_and_child_df = pd.merge(adult_scores_df, child_scores_df, on='ID', how='outer')
        all_scores_df = pd.merge(adult_and_child_df, infant_scores_df, on='ID', how='outer')

        # Merge all_scores with original file
        final_output_df = pd.merge(enrollee_df, all_scores_df, on='ID', how='left')
        
        # Select intermediate output according to configurable switches 
        if run_spec['intermediate_variable_output_switches']['demographic_age_sex'] == True:
            final_output_df = final_output_df.merge(
                enrollee_age_sex_df[demographic_age_sex_col_names + ['ID']], on='ID', how='left')
        
        if run_spec['intermediate_variable_output_switches']['cc_assignments'] == True:
            enrollee_diagnosis_cc_df = enrollee_diagnosis_cc_df.rename(columns={col: col.replace(
                'HHS_CC', 'CC') for col in enrollee_diagnosis_cc_df.columns if col.startswith('HHS_CC')})
            final_output_df = final_output_df.merge(
                enrollee_diagnosis_cc_df, on='ID', how='left')
        
        if run_spec['intermediate_variable_output_switches']['hcc_assignments'] == True:
            hcc_col_names = [col for col in enrollee_hcc_df.columns if col.startswith('HHS_HCC')]
            enrollee_hcc_df = enrollee_hcc_df.rename(columns={col: col.replace('HHS_HCC', 'HCC') for col in hcc_col_names})
            final_output_df = final_output_df.merge(
                enrollee_hcc_df[[col for col in enrollee_hcc_df if col.startswith('HCC')] + ['ID']], on='ID', how='left')
        
        if run_spec['intermediate_variable_output_switches']['hhs_hcc_assignments'] == True:
            # Get post grouping vars for output with intermediates
            common_cols = [col for col in adult_model_vars_df.columns if col == "ID" or col.startswith("HHS_HCC")]
            post_grouping_vars = adult_model_vars_df[common_cols]
            post_grouping_vars = post_grouping_vars.merge(
                child_model_vars_df[common_cols],
                on=common_cols, how="outer"
            )
            post_grouping_vars = post_grouping_vars.merge(
                infant_model_vars_df[common_cols],
                on=common_cols, how="outer"
            )
            final_output_df = final_output_df.merge(
                post_grouping_vars, on='ID', how='left')
        
        if run_spec['intermediate_variable_output_switches']['rxc_assignments'] == True:
            add_on_cols = rxc_vars_df.columns.drop('ID')
            rxc_vars_df[add_on_cols] = rxc_vars_df[add_on_cols].fillna(0).astype(int)
            final_output_df = final_output_df.merge(
                rxc_vars_df, on='ID', how='left')
            # Columns that came from rxc_vars_df (excluding ID)
            rxc_cols = rxc_vars_df.columns.difference(['ID'])

            # Fill missing values from the merge and cast to int
            final_output_df[rxc_cols] = (
                final_output_df[rxc_cols]
                    .fillna(0)
                    .astype(int)
            )
        
        if run_spec['intermediate_variable_output_switches']['rxc_hcc_interactions'] == True:
            rxc_hcc_interaction_cols = RXC_interactions['RXC_interaction'].tolist()
            final_output_df = final_output_df.merge(
                adult_model_vars_df[rxc_hcc_interaction_cols + ['ID']], on='ID', how='left')

            # Fill missing values from the merge and cast to int
            final_output_df[rxc_hcc_interaction_cols] = (
                final_output_df[rxc_hcc_interaction_cols]
                    .fillna(0)
                    .astype(int)
            )
        
        if run_spec['intermediate_variable_output_switches']['hcc_groups_and_interactions'] == True:
            hcc_adult_group_cols = adult_group_mappings['Group'].tolist()
            final_output_df = final_output_df.merge(
                adult_model_vars_df[hcc_adult_group_cols + ['ID']], on='ID', how='left')
            #Fill missing values from the merge and cast to int
            final_output_df[hcc_adult_group_cols] = (
                final_output_df[hcc_adult_group_cols]
                    .fillna(0)
                    .astype(int)
            )
            hcc_child_group_cols = child_group_mappings['Group'].tolist()
            join_cols = ["ID"] + [col for col in hcc_child_group_cols if col in hcc_adult_group_cols]
            final_output_df = final_output_df.merge(
                child_model_vars_df[hcc_child_group_cols + ['ID']], on=join_cols, how='left')
            # Fill missing values from the merge and cast to int
            final_output_df[hcc_child_group_cols] = (
                final_output_df[hcc_child_group_cols]
                    .fillna(0)
                    .astype(int)
            )
        
        if run_spec['intermediate_variable_output_switches']['severe_and_transplant_indicators_and_interactions'] == True:
            adult_subset_df = adult_model_vars_df[['ID', "SEVERE", "TRANSPLANT"] + [col for col in adult_model_vars_df.columns if 
                                              col.startswith('TRANSPLANT_HCC_COUNT') or col.startswith('SEVERE_HCC_COUNT')]
                                             ]
            child_subset_df = child_model_vars_df[['ID', "SEVERE", "TRANSPLANT"] + [col for col in child_model_vars_df.columns if
                                                                               col.startswith('TRANSPLANT_HCC_COUNT') or col.startswith('SEVERE_HCC_COUNT')]
                                             ]
            all_subset_df = pd.concat([adult_subset_df, child_subset_df], axis=0).fillna(0)
            final_output_df = final_output_df.merge(all_subset_df, on='ID', how='left')
            # Fill missing values from the merge and cast to int
            severe_transplant_cols = [col for col in all_subset_df.columns if col != 'ID']
            final_output_df[severe_transplant_cols] = (
                final_output_df[severe_transplant_cols]
                    .fillna(0)
                    .astype(int)
            )
        
        if run_spec['intermediate_variable_output_switches']['adult_hcc_contingent_enrollment_indicators'] == True:
            adult_subset_df = adult_model_vars_df[['ID'] + [col for col in adult_model_vars_df.columns if col.startswith('HCC_ED')]]
            final_output_df = final_output_df.merge(adult_subset_df, on='ID', how='left')
            # Fill missing values from the merge and cast to int
            adult_hcc_ed_cols = [col for col in adult_subset_df.columns if col != 'ID']
            final_output_df[adult_hcc_ed_cols] = (
                final_output_df[adult_hcc_ed_cols]
                    .fillna(0)
                    .astype(int)
            )
        
        if run_spec['intermediate_variable_output_switches']['infant_model_assignments_and_interactions'] == True:
            maturity_cols = [
                'IHCC_EXTREMELY_IMMATURE',
                'IHCC_IMMATURE',
                'IHCC_PREMATURE_MULTIPLES',
                'IHCC_TERM'
            ]
            severity_level_cols = [col for col in infant_model_vars_df.columns if col.startswith('IHCC_SEVERITY')]
            severity_level_interaction_cols = [col for col in infant_model_vars_df.columns if 'X_SEVERITY' in col]
            infant_subset_df = infant_model_vars_df[[
                "ID"] + maturity_cols + severity_level_cols + severity_level_interaction_cols]
            final_output_df = final_output_df.merge(infant_subset_df, on='ID', how='left')
            # Fill missing values from the merge and cast to int
            infant_cols = [col for col in infant_subset_df.columns if col != 'ID']
            final_output_df[infant_cols] = (
                final_output_df[infant_cols]
                    .fillna(0)
                    .astype(int)
            )
        
        # If column contains "SCORE", fill missing values with 0
        score_cols = [col for col in final_output_df.columns if 'SCORE' in col]
        final_output_df[score_cols] = final_output_df[score_cols].fillna(0)
        # Round score columns to 3 decimal places
        final_output_df[score_cols] = final_output_df[score_cols].round(3)
        
        # Write to csv
        final_output_df.to_csv(filepaths['output_filepath'], index=False)
        
        logging.info(f"Model scores written to {filepaths['output_filepath']}")
        logging.info('Complete - exiting program')
        print('Transformation complete.')
        log_filepath = filepaths['log_output_filepath']
        print(f'log file saved to {log_filepath}')
        print(f"score output file saved to {filepaths['output_filepath']}")
        
    except Exception as e:
        logging.error(f'Error occurred: {e}')
        print(f'Error occurred: {e}')
        raise e
        
if __name__ == "__main__": 
    transform_hhs_hcc_scores(run_spec, main_filepaths)
