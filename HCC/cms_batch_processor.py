"""
CMS HHS-HCC Batch Processor
===========================
A batch processing module that wraps the official CMS HHS-HCC Python software package.
It maps user datasets, formats the required PERSON/DIAGNOSES files, runs the official 
transformation pipeline via subprocess, and merges the detailed risk scores and 
intermediate variables back to the input dataset.

Author: Antigravity AI
"""

import os
import re
import sys
import json
import time
import shutil
import subprocess
import pandas as pd
from typing import List, Dict, Any, Union, Optional

class CMSHHSCCBatchProcessor:
    def __init__(self, cms_software_dir: Optional[str] = None):
        """
        Initialize the CMS HHS-HCC Batch Processor.
        
        Args:
            cms_software_dir: Path to the extracted official CMS software directory
                              containing the 'software' folder.
        """
        if cms_software_dir is None:
            # Default workspace path
            self.cms_software_dir = r"e:\Personal\HCC\cms_hhs_hcc_python\HHS_HCC_software_package_V0825.141.E3"
        else:
            self.cms_software_dir = os.path.abspath(cms_software_dir)
            
        # Verify paths
        self.software_path = os.path.join(self.cms_software_dir, "software")
        self.hhs_hcc_path = os.path.join(self.software_path, "HHS_HCC")
        self.user_defined_dir = os.path.join(self.hhs_hcc_path, "data", "input", "user_defined")
        self.output_dir = os.path.join(self.hhs_hcc_path, "data", "output")
        
        if not os.path.exists(self.cms_software_dir):
            raise FileNotFoundError(f"CMS software package directory not found: {self.cms_software_dir}")
        if not os.path.exists(self.user_defined_dir):
            raise FileNotFoundError(f"CMS user_defined data folder not found: {self.user_defined_dir}")

        # Set default files
        self.person_csv = os.path.join(self.user_defined_dir, "PERSON.csv")
        self.diagnoses_csv = os.path.join(self.user_defined_dir, "DIAGNOSES.csv")
        self.ndc_csv = os.path.join(self.user_defined_dir, "NDC.csv")
        self.hcpcs_csv = os.path.join(self.user_defined_dir, "HCPCS.csv")
        
        # Default CMS benefit year configuration (matches config.py)
        self.benefit_year = 2025

    def detect_columns(self, df: pd.DataFrame) -> Dict[str, Optional[str]]:
        """
        Auto-detect demographic, diagnosis, drug and procedure columns in a DataFrame.
        """
        cols = [c.lower() for c in df.columns]
        col_map = {
            "id": None,
            "age": None,
            "sex": None,
            "dx": None,
            "dob": None,
            "metal": None,
            "csr": None,
            "enrol": None,
            "date": None,
            "ndc": None,
            "hcpcs": None
        }

        # Regex patterns for matching
        id_patterns = [r'^patient_?id$', r'^pat_?id$', r'^id$', r'^patient_?no$', r'^member_?id$', r'^pid$']
        age_patterns = [r'^age$', r'^age_?yrs$', r'^age_?years$', r'^pt_?age$', r'^patient_?age$', r'^age_?last$']
        sex_patterns = [r'^sex$', r'^gender$', r'^gender_?cd$', r'^pt_?sex$', r'^patient_?sex$', r'^sex_?cd$']
        dx_patterns = [r'^dx$', r'^diagnosis$', r'^diagnoses$', r'^icd10$', r'^icd_?codes$', r'^diagnosis_?codes$', r'^dx_?codes$']
        dob_patterns = [r'^dob$', r'^date_?of_?birth$', r'^birth_?date$', r'^pt_?dob$']
        metal_patterns = [r'^metal$', r'^metal_?level$', r'^plan_?level$', r'^plan_?metal$']
        csr_patterns = [r'^csr$', r'^csr_?indicator$', r'^csr_?ind$']
        enrol_patterns = [r'^enrol_?duration$', r'^enrollment_?duration$', r'^enrolduration$', r'^months_?enrolled$']
        date_patterns = [r'^service_?date$', r'^diagnosis_?service_?date$', r'^diag_?date$', r'^dx_?date$']
        ndc_patterns = [r'^ndc$', r'^ndc_?code$', r'^ndc_?codes$', r'^drugs$', r'^drug_?codes$']
        hcpcs_patterns = [r'^hcpcs$', r'^hcpcs_?code$', r'^hcpcs_?codes$', r'^procedure_?codes$', r'^procedures$']

        # Match columns
        for original_col in df.columns:
            col_lower = original_col.lower()
            
            if not col_map["id"] and any(re.match(p, col_lower) for p in id_patterns):
                col_map["id"] = original_col
            elif not col_map["age"] and any(re.match(p, col_lower) for p in age_patterns):
                col_map["age"] = original_col
            elif not col_map["sex"] and any(re.match(p, col_lower) for p in sex_patterns):
                col_map["sex"] = original_col
            elif not col_map["dx"] and any(re.match(p, col_lower) for p in dx_patterns):
                col_map["dx"] = original_col
            elif not col_map["dob"] and any(re.match(p, col_lower) for p in dob_patterns):
                col_map["dob"] = original_col
            elif not col_map["metal"] and any(re.match(p, col_lower) for p in metal_patterns):
                col_map["metal"] = original_col
            elif not col_map["csr"] and any(re.match(p, col_lower) for p in csr_patterns):
                col_map["csr"] = original_col
            elif not col_map["enrol"] and any(re.match(p, col_lower) for p in enrol_patterns):
                col_map["enrol"] = original_col
            elif not col_map["date"] and any(re.match(p, col_lower) for p in date_patterns):
                col_map["date"] = original_col
            elif not col_map["ndc"] and any(re.match(p, col_lower) for p in ndc_patterns):
                col_map["ndc"] = original_col
            elif not col_map["hcpcs"] and any(re.match(p, col_lower) for p in hcpcs_patterns):
                col_map["hcpcs"] = original_col

        # Fallbacks
        if not col_map["id"] and len(df.columns) > 0:
            col_map["id"] = df.columns[0]
            
        return col_map

    def parse_codes(self, val: Any) -> List[str]:
        """
        Parse and clean diagnosis, NDC, or HCPCS codes.
        Removes dots and special characters to ensure dotless codes.
        """
        if pd.isna(val) or val is None:
            return []
            
        raw_list = []
        if isinstance(val, (list, set, tuple)):
            raw_list = [str(code).strip() for code in val]
        elif isinstance(val, str):
            val_str = val.strip()
            if not val_str:
                return []
            
            # Check JSON array
            if val_str.startswith('[') and val_str.endswith(']'):
                try:
                    parsed = json.loads(val_str)
                    if isinstance(parsed, list):
                        raw_list = [str(code).strip() for code in parsed]
                except Exception:
                    pass
            
            # If not JSON, split by common delimiters
            if not raw_list:
                for d in [',', ';', '|']:
                    if d in val_str:
                        raw_list = [c.strip() for c in val_str.split(d)]
                        break
            
            if not raw_list:
                raw_list = [c.strip() for c in val_str.split()]
        else:
            raw_list = [str(val).strip()]

        # Clean codes: uppercase, remove all dots/spaces/non-alphanumeric
        clean_list = []
        for code in raw_list:
            clean = re.sub(r'[^a-zA-Z0-9]', '', code).upper()
            if clean:
                clean_list.append(clean)
        return clean_list

    def normalize_sex(self, val: Any) -> int:
        """
        Normalize sex/gender into CMS integer format:
        1 = Male, 2 = Female.
        """
        if pd.isna(val) or val is None:
            raise ValueError("Sex/gender field is missing.")
            
        s = str(val).strip().upper()
        if not s:
            raise ValueError("Sex/gender field is empty.")
            
        if s.startswith('M') or s == '1':
            return 1
        elif s.startswith('F') or s == '2' or s.startswith('W'):
            return 2
        else:
            raise ValueError(f"Invalid sex/gender: '{val}'. Must be M/F, Male/Female, or 1/2.")

    def clear_user_defined_files(self):
        """Clear all PERSON, DIAGNOSES, NDC, and HCPCS files in the CMS input folder."""
        for path, header in [
            (self.person_csv, "ID,SEX,DOB,AGE_LAST,METAL,CSR_INDICATOR,ENROLDURATION"),
            (self.diagnoses_csv, "ID,ICD10,DIAGNOSIS_SERVICE_DATE"),
            (self.ndc_csv, "ID,NDC"),
            (self.hcpcs_csv, "ID,HCPCS")
        ]:
            if os.path.exists(path):
                os.remove(path)
            # Create fresh file with header
            with open(path, 'w', encoding='utf-8') as f:
                f.write(header + "\n")

    def format_inputs(self, df: pd.DataFrame, col_map: Dict[str, Optional[str]], wide_dx_cols: Optional[List[str]] = None):
        """
        Convert user DataFrame to CMS format and write to user_defined CSVs.
        """
        self.clear_user_defined_files()
        
        # Resolve column names
        id_col = col_map["id"]
        age_col = col_map["age"]
        sex_col = col_map["sex"]
        dx_col = col_map["dx"]
        dob_col = col_map["dob"]
        metal_col = col_map["metal"]
        csr_col = col_map["csr"]
        enrol_col = col_map["enrol"]
        date_col = col_map["date"]
        ndc_col = col_map["ndc"]
        hcpcs_col = col_map["hcpcs"]
        
        # 1. Prepare lists for csv writing
        person_rows = []
        diag_rows = []
        ndc_rows = []
        hcpcs_rows = []
        
        print("Formatting user data into CMS requirements...")
        
        for idx, row in df.iterrows():
            pat_id = str(row[id_col]).strip()
            
            # Demographics
            sex_val = self.normalize_sex(row[sex_col])
            
            # Age LAST
            if pd.isna(row[age_col]):
                raise ValueError(f"Missing age for patient {pat_id}")
            age_last = int(float(row[age_col]))
            
            # DOB (calculate dummy if not present)
            if dob_col and not pd.isna(row[dob_col]):
                # Parse DOB, format as YYYYMMDD
                dob_raw = str(row[dob_col]).strip()
                dob_num = re.sub(r'\D', '', dob_raw)
                if len(dob_num) == 8:
                    dob = dob_num
                else:
                    dob = pd.to_datetime(dob_raw).strftime("%Y%m%d")
            else:
                birth_year = self.benefit_year - age_last
                dob = f"{birth_year}0101"
                
            # Optional Plan variables
            metal = str(row[metal_col]).strip().upper() if metal_col and not pd.isna(row[metal_col]) else "S"
            if metal not in ('P', 'G', 'S', 'B', 'C'):
                metal = "S"
                
            csr = int(float(row[csr_col])) if csr_col and not pd.isna(row[csr_col]) else 1
            enrol = int(float(row[enrol_col])) if enrol_col and not pd.isna(row[enrol_col]) else 12
            
            person_rows.append({
                "ID": pat_id,
                "SEX": sex_val,
                "DOB": dob,
                "AGE_LAST": age_last,
                "METAL": metal,
                "CSR_INDICATOR": csr,
                "ENROLDURATION": enrol
            })
            
            # Diagnosis Service Date
            if date_col and not pd.isna(row[date_col]):
                date_raw = str(row[date_col]).strip()
                date_num = re.sub(r'\D', '', date_raw)
                if len(date_num) == 8:
                    service_date = date_num
                else:
                    service_date = pd.to_datetime(date_raw).strftime("%Y%m%d")
            else:
                service_date = f"{self.benefit_year}0601"
                
            # Parse diagnoses
            dx_codes = []
            if dx_col and not pd.isna(row[dx_col]):
                dx_codes.extend(self.parse_codes(row[dx_col]))
            if wide_dx_cols:
                for wcol in wide_dx_cols:
                    if wcol in row and not pd.isna(row[wcol]):
                        dx_codes.extend(self.parse_codes(row[wcol]))
                        
            dx_codes = list(dict.fromkeys(dx_codes))
            if not dx_codes:
                # Add a dummy record to ensure every patient has at least one diagnosis record.
                # This prevents float casting / nan issues in the CMS code left-join date parsing.
                diag_rows.append({
                    "ID": pat_id,
                    "ICD10": "NONE",
                    "DIAGNOSIS_SERVICE_DATE": service_date
                })
            else:
                for code in dx_codes:
                    diag_rows.append({
                        "ID": pat_id,
                        "ICD10": code,
                        "DIAGNOSIS_SERVICE_DATE": service_date
                    })
                
            # Drugs (NDCs)
            if ndc_col and not pd.isna(row[ndc_col]):
                ndcs = self.parse_codes(row[ndc_col])
                for ndc in ndcs:
                    ndc_rows.append({"ID": pat_id, "NDC": ndc})
                    
            # Procedures (HCPCS)
            if hcpcs_col and not pd.isna(row[hcpcs_col]):
                hcpcss = self.parse_codes(row[hcpcs_col])
                for hcpcs in hcpcss:
                    hcpcs_rows.append({"ID": pat_id, "HCPCS": hcpcs})

        # 2. Write CSVs
        person_df = pd.DataFrame(person_rows)
        if not person_df.empty:
            person_df["ID"] = person_df["ID"].astype(str)
            person_df["DOB"] = person_df["DOB"].astype(str)
            person_df["METAL"] = person_df["METAL"].astype(str)
            person_df["SEX"] = person_df["SEX"].astype(int)
            person_df["AGE_LAST"] = person_df["AGE_LAST"].astype(int)
            person_df["CSR_INDICATOR"] = person_df["CSR_INDICATOR"].astype(int)
            person_df["ENROLDURATION"] = person_df["ENROLDURATION"].astype(int)
        person_df.to_csv(self.person_csv, index=False)
        
        if diag_rows:
            diag_df = pd.DataFrame(diag_rows)
            diag_df["ID"] = diag_df["ID"].astype(str)
            diag_df["ICD10"] = diag_df["ICD10"].astype(str)
            diag_df["DIAGNOSIS_SERVICE_DATE"] = diag_df["DIAGNOSIS_SERVICE_DATE"].astype(str)
            diag_df.to_csv(self.diagnoses_csv, index=False)
            
        if ndc_rows:
            ndc_df = pd.DataFrame(ndc_rows)
            ndc_df["ID"] = ndc_df["ID"].astype(str)
            ndc_df["NDC"] = ndc_df["NDC"].astype(str)
            ndc_df.to_csv(self.ndc_csv, index=False)
            
        if hcpcs_rows:
            hcpcs_df = pd.DataFrame(hcpcs_rows)
            hcpcs_df["ID"] = hcpcs_df["ID"].astype(str)
            hcpcs_df["HCPCS"] = hcpcs_df["HCPCS"].astype(str)
            hcpcs_df.to_csv(self.hcpcs_csv, index=False)
            
        print(f"Data formatted and written to CMS inputs folder:")
        print(f"  - PERSON.csv    : {len(person_rows)} records")
        print(f"  - DIAGNOSES.csv : {len(diag_rows)} diagnosis mappings")
        print(f"  - NDC.csv       : {len(ndc_rows)} drug mappings")
        print(f"  - HCPCS.csv     : {len(hcpcs_rows)} procedure mappings")

    def run_cms_transform(self) -> bool:
        """
        Execute the official CMS transformation pipeline inside a subprocess.
        """
        print("Launching official CMS transform.py pipeline in subprocess...")
        start_time = time.time()
        
        # Prepare command
        python_executable = sys.executable or "python"
        script_path = os.path.join("software", "HHS_HCC", "transform.py")
        
        # Run subprocess
        result = subprocess.run(
            [python_executable, script_path],
            cwd=self.cms_software_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        duration = time.time() - start_time
        print(f"CMS transformation subprocess finished in {duration:.2f} seconds.")
        
        if result.returncode == 0:
            print("CMS Pipeline executed successfully.")
            return True
        else:
            print("CMS Pipeline failed!")
            print("--- Subprocess Stdout ---")
            print(result.stdout)
            print("--- Subprocess Stderr ---")
            print(result.stderr)
            return False

    def load_cms_results(self) -> pd.DataFrame:
        """
        Read the generated scores output from the CMS output directory.
        """
        # Find output files in the output directory
        files = os.listdir(self.output_dir)
        score_files = [f for f in files if f.endswith("_scores.csv")]
        
        if not score_files:
            raise FileNotFoundError(f"No score output file found in {self.output_dir}")
            
        # Sort and take latest or default name
        score_file_name = score_files[0]
        score_filepath = os.path.join(self.output_dir, score_file_name)
        print(f"Loading CMS scores output from {score_filepath}...")
        
        df = pd.read_csv(score_filepath, dtype={"ID": str})
        return df

    def cleanup_cms_directories(self):
        """Clean all user_defined files and output files from CMS package directories."""
        self.clear_user_defined_files()
        
        # Clear files in output directory
        if os.path.exists(self.output_dir):
            for file in os.listdir(self.output_dir):
                filepath = os.path.join(self.output_dir, file)
                try:
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                except Exception as e:
                    print(f"Warning: could not delete {filepath}: {e}")

    def process_dataframe(self, df: pd.DataFrame, id_col: Optional[str] = None, age_col: Optional[str] = None, 
                          sex_col: Optional[str] = None, dx_col: Optional[str] = None, 
                          dob_col: Optional[str] = None, metal_col: Optional[str] = None, 
                          csr_col: Optional[str] = None, enrol_col: Optional[str] = None, 
                          date_col: Optional[str] = None, ndc_col: Optional[str] = None,
                          hcpcs_col: Optional[str] = None, wide_dx_cols: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Process the given DataFrame, calculate risk scores using official CMS package, 
        and return the merged DataFrame with calculations.
        """
        # Auto-detect columns
        detected = self.detect_columns(df)
        id_col = id_col or detected["id"]
        age_col = age_col or detected["age"]
        sex_col = sex_col or detected["sex"]
        dx_col = dx_col or detected["dx"]
        dob_col = dob_col or detected["dob"]
        metal_col = metal_col or detected["metal"]
        csr_col = csr_col or detected["csr"]
        enrol_col = enrol_col or detected["enrol"]
        date_col = date_col or detected["date"]
        ndc_col = ndc_col or detected["ndc"]
        hcpcs_col = hcpcs_col or detected["hcpcs"]
        
        # Validate columns
        if not id_col or not age_col or not sex_col:
            raise ValueError(
                f"Missing required columns. ID={id_col}, Age={age_col}, Sex={sex_col}. "
                f"Please specify column names explicitly if auto-detection failed."
            )
            
        col_map = {
            "id": id_col, "age": age_col, "sex": sex_col, "dx": dx_col,
            "dob": dob_col, "metal": metal_col, "csr": csr_col, "enrol": enrol_col,
            "date": date_col, "ndc": ndc_col, "hcpcs": hcpcs_col
        }
        
        print("\n" + "="*50)
        print("          OFFICIAL CMS HHS-HCC BATCH RUN")
        print("="*50)
        print(f"Columns Mapped:")
        for k, v in col_map.items():
            if v:
                print(f"  - {k.upper():10s}: {v}")
        if wide_dx_cols:
            print(f"  - WIDE DX   : {wide_dx_cols}")
        print("-"*50)
        
        # 1. Format inputs and write CSV files
        self.format_inputs(df, col_map, wide_dx_cols)
        
        # 2. Run official CMS transformation script
        success = self.run_cms_transform()
        if not success:
            # Cleanup and raise
            self.cleanup_cms_directories()
            raise RuntimeError("CMS transformation execution failed. Check console error outputs above.")
            
        # 3. Load results
        scores_df = self.load_cms_results()
        
        # 4. Clean up CMS folders immediately to avoid clutter
        print("Cleaning up temporary files from CMS folders...")
        self.cleanup_cms_directories()
        
        # 5. Join scores back to user DataFrame
        # Convert ID to string in both for exact merging
        df_copy = df.copy()
        df_copy['_join_id'] = df_copy[id_col].astype(str).str.strip()
        scores_df['_join_id'] = scores_df['ID'].astype(str).str.strip()
        
        # Drop columns in scores_df that are duplicate to original input columns (except ID or scores)
        cms_meta_cols = ['DOB', 'SEX', 'METAL', 'CSR_INDICATOR', 'ENROLDURATION', 'AGE_LAST', 'ID']
        score_cols = [c for c in scores_df.columns if c not in cms_meta_cols and c != '_join_id']
        
        # Merge only the score/flag columns
        merged_df = df_copy.merge(scores_df[['_join_id'] + score_cols], on='_join_id', how='left')
        merged_df = merged_df.drop(columns=['_join_id'])
        
        # Print summary statistics
        self._print_summary_report(merged_df)
        
        return merged_df

    def process_file(self, input_path: str, output_path: str, id_col: Optional[str] = None, 
                     age_col: Optional[str] = None, sex_col: Optional[str] = None, 
                     dx_col: Optional[str] = None, dob_col: Optional[str] = None, 
                     metal_col: Optional[str] = None, csr_col: Optional[str] = None, 
                     enrol_col: Optional[str] = None, date_col: Optional[str] = None, 
                     ndc_col: Optional[str] = None, hcpcs_col: Optional[str] = None, 
                     wide_dx_cols: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Process a CSV or Excel file containing patient records, run CMS tool,
        and write the results containing risk scores to the output path.
        """
        file_ext = os.path.splitext(input_path)[1].lower()
        if file_ext in ('.xlsx', '.xls'):
            print(f"Reading Excel file: {input_path}")
            df = pd.read_excel(input_path)
        else:
            print(f"Reading CSV file: {input_path}")
            df = pd.read_csv(input_path)
            
        output_df = self.process_dataframe(
            df, id_col=id_col, age_col=age_col, sex_col=sex_col, dx_col=dx_col,
            dob_col=dob_col, metal_col=metal_col, csr_col=csr_col, enrol_col=enrol_col,
            date_col=date_col, ndc_col=ndc_col, hcpcs_col=hcpcs_col, wide_dx_cols=wide_dx_cols
        )
        
        # Save output
        if file_ext in ('.xlsx', '.xls'):
            print(f"Writing Excel output file: {output_path}")
            output_df.to_excel(output_path, index=False)
        else:
            print(f"Writing CSV output file: {output_path}")
            output_df.to_csv(output_path, index=False)
            
        return output_df

    def _print_summary_report(self, df: pd.DataFrame):
        """
        Generate and print a summary report from the final scored DataFrame.
        """
        total_rows = len(df)
        
        score_cols = [c for c in df.columns if 'SCORE' in c]
        main_score_cols = [c for c in score_cols if c in ('SCORE_ADULT', 'SCORE_CHILD', 'SCORE_INFANT')]
        
        print("\n" + "="*50)
        print("          CMS BATCH RUN SUMMARY REPORT")
        print("="*50)
        print(f"Total Patients Scored : {total_rows:,}")
        print("-"*50)
        
        for col in main_score_cols:
            non_zero = df[df[col] > 0]
            avg = df[col].mean()
            print(f"Average {col:15s} : {avg:.4f} (based on {len(non_zero)} non-zero scores)")
            
        print("-"*50)
        hcc_cols = [c for c in df.columns if c.startswith('HCC') and c[3:].isdigit()]
        
        active_hccs = {}
        for hcc in hcc_cols:
            count = (df[hcc] == 1).sum()
            if count > 0:
                active_hccs[hcc] = count
                
        print(f"Unique HCC Categories Mapped: {len(active_hccs)}")
        if active_hccs:
            print("Top 10 Most Common Mapped HCCs:")
            sorted_hccs = sorted(active_hccs.items(), key=lambda x: x[1], reverse=True)[:10]
            for rank, (hcc, count) in enumerate(sorted_hccs, 1):
                pct = (count / total_rows) * 100
                print(f"  {rank:2d}. {hcc:7s} : {count:5,} patients ({pct:.2f}%)")
        else:
            print("  No HCCs mapped in this dataset.")
        print("="*50 + "\n")
