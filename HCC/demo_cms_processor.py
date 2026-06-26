"""
Demo Script for CMS HHS-HCC Batch Processor
===========================================
This script demonstrates the usage of the CMSHHSCCBatchProcessor by generating 
mock patient data (with dot-based diagnoses like E11.9, age, and sex), 
running the official CMS scoring transformation pipeline, and outputting the results.

Author: Antigravity AI
"""

import os
import random
import pandas as pd
from cms_batch_processor import CMSHHSCCBatchProcessor

def generate_mock_patients(num_records: int = 100) -> pd.DataFrame:
    """Generate realistic mock patients for testing."""
    print(f"Generating {num_records} mock patient records...")
    
    # Common codes mapping to HCC categories in HHS-HCC (with dots)
    hcc_icd10_codes = [
        "E11.9",    # Type 2 diabetes mellitus without complications -> CC 137
        "N18.3",    # Chronic kidney disease, stage 3 -> CC 163
        "I50.9",    # Heart failure, unspecified -> CC 135
        "C34.90",   # Malignant neoplasm of bronchus or lung -> CC 11
        "J44.9",    # COPD -> CC 138
        "F32.9",    # Major depressive disorder -> CC 69
        "Z99.81",   # Dependence on supplemental oxygen -> CC 142
        "E11.69",   # Type 2 diabetes mellitus with other specified complications -> CC 137
        "I12.9"     # Hypertensive chronic kidney disease -> CC 163
    ]
    
    # Non-HCC ICD-10 codes (with and without dots)
    non_hcc_icd10_codes = [
        "I10",      # Essential hypertension
        "M17.9",    # Osteoarthritis of knee
        "M81.0",    # Age-related osteoporosis
        "Z00.00",   # General adult medical exam
        "R51.9",    # Headache
        "K21.9",    # GERD
        "H10.9"     # Unspecified conjunctivitis
    ]
    
    all_codes = hcc_icd10_codes + non_hcc_icd10_codes
    genders = ["M", "F", "Male", "Female"]
    metals = ["P", "G", "S", "B", "C"] # Platinum, Gold, Silver, Bronze, Catastrophic
    
    patients = []
    for i in range(1, num_records + 1):
        pat_id = f"DEMO_PAT_{i:04d}"
        
        # Age distribution
        age = int(random.normalvariate(50, 18))
        age = max(1, min(95, age))
        
        gender = random.choice(genders)
        metal = random.choices(metals, weights=[0.1, 0.2, 0.5, 0.15, 0.05])[0]
        
        # Random diagnoses
        num_dx = random.choices([0, 1, 2, 3, 4], weights=[0.1, 0.4, 0.3, 0.15, 0.05])[0]
        chosen_dx = random.sample(all_codes, k=min(num_dx, len(all_codes))) if num_dx > 0 else []
        
        # Vary delimiters
        delim = random.choice([",", ";", "|"])
        dx_str = delim.join(chosen_dx)
        
        patients.append({
            "PatientID": pat_id,
            "Age": age,
            "Gender": gender,
            "MetalLevel": metal,
            "DiagnosisCodes": dx_str
        })
        
    return pd.DataFrame(patients)

def main():
    # 1. Initialize processor
    # Uses default directory: e:\Personal\HCC\cms_hhs_hcc_python\HHS_HCC_software_package_V0825.141.E3
    try:
        processor = CMSHHSCCBatchProcessor()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please check that the official CMS package is extracted in the default location.")
        return

    # 2. Generate 1,000 mock patients
    df_patients = generate_mock_patients(1000)
    
    # 3. Save mock input for user reference
    mock_input_path = "demo_patients_input.csv"
    df_patients.to_csv(mock_input_path, index=False)
    print(f"Saved input mock data to: {mock_input_path}")
    
    # 4. Run batch processor
    # Auto-detection matches:
    #   - PatientID -> ID
    #   - Age -> AGE_LAST
    #   - Gender -> SEX (M/F -> 1/2)
    #   - MetalLevel -> METAL
    #   - DiagnosisCodes -> ICD10
    output_path = "demo_patients_scored.csv"
    
    print("\nStarting batch scoring using the official CMS tool...")
    scored_df = processor.process_dataframe(
        df_patients,
        id_col="PatientID",
        age_col="Age",
        sex_col="Gender",
        dx_col="DiagnosisCodes",
        metal_col="MetalLevel"
    )
    
    # Save output
    scored_df.to_csv(output_path, index=False)
    print(f"Scored results saved to: {output_path}")
    
    # 5. Display sample results
    print("\n--- SAMPLE PATIENT SCORES ---")
    score_cols = [c for c in scored_df.columns if 'SCORE' in c and 'CSR' not in c]
    # Filter columns to display nicely
    disp_cols = ["PatientID", "Age", "Gender", "MetalLevel", "DiagnosisCodes"] + score_cols[:3]
    print(scored_df[disp_cols].head(10).to_string(index=False))

if __name__ == "__main__":
    main()
