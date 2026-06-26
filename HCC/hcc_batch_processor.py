"""
HCC Batch Processor
===================
A high-performance batch processing module for Hierarchical Condition Category (HCC) 
risk adjustment calculations. Designed to handle large patient datasets (CSV or Excel) 
efficiently while maintaining low memory usage.

Author: Antigravity AI
"""

import os
import re
import json
import time
import random
from typing import List, Dict, Any, Union, Iterable, Optional
import pandas as pd
from tqdm import tqdm
from hccinfhir import HCCInFHIR

class HCCBatchProcessor:
    def __init__(self, model_name: str = "CMS-HCC Model V28", **kwargs):
        """
        Initialize the HCC Batch Processor.
        
        Args:
            model_name: The CMS-HCC or RxHCC model to use.
                       Defaults to "CMS-HCC Model V28".
            **kwargs: Additional parameters passed to HCCInFHIR initialization.
        """
        self.model_name = model_name
        print(f"Initializing HCCInFHIR with model: {model_name}...")
        self.processor = HCCInFHIR(model_name=model_name, **kwargs)
        print("Initialization complete.")

    def detect_columns(self, df: pd.DataFrame) -> Dict[str, Optional[str]]:
        """
        Auto-detect demographic and diagnosis columns in a DataFrame.
        
        Args:
            df: Input pandas DataFrame
            
        Returns:
            Dictionary containing mapped column names for 'id', 'age', 'sex', and 'dx'.
        """
        cols = [c.lower() for c in df.columns]
        col_map = {
            "id": None,
            "age": None,
            "sex": None,
            "dx": None
        }

        # Regex patterns for matching
        id_patterns = [r'^patient_?id$', r'^pat_?id$', r'^id$', r'^patient_?no$', r'^member_?id$', r'^pid$']
        age_patterns = [r'^age$', r'^age_?yrs$', r'^age_?years$', r'^pt_?age$', r'^patient_?age$']
        sex_patterns = [r'^sex$', r'^gender$', r'^gender_?cd$', r'^pt_?sex$', r'^patient_?sex$', r'^sex_?cd$']
        dx_patterns = [r'^dx$', r'^diagnosis$', r'^diagnoses$', r'^icd10$', r'^icd_?codes$', r'^diagnosis_?codes$', r'^dx_?codes$']

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

        # Fallbacks
        if not col_map["id"] and len(df.columns) > 0:
            # Fallback to first column as ID if no clear match
            col_map["id"] = df.columns[0]
            
        return col_map

    def parse_diagnosis_codes(self, val: Any) -> List[str]:
        """
        Parse diagnosis codes from various input formats.
        
        Args:
            val: Raw field value (can be string, list, JSON string, NaN, etc.)
            
        Returns:
            A clean list of diagnosis code strings.
        """
        if pd.isna(val) or val is None:
            return []
            
        if isinstance(val, (list, set, tuple)):
            return [str(code).strip() for code in val if str(code).strip()]

        if isinstance(val, str):
            val_str = val.strip()
            if not val_str:
                return []
            
            # Check if it looks like a JSON array, e.g., ["E11.9", "I10"]
            if val_str.startswith('[') and val_str.endswith(']'):
                try:
                    parsed = json.loads(val_str)
                    if isinstance(parsed, list):
                        return [str(code).strip() for code in parsed if str(code).strip()]
                except Exception:
                    pass # Fallback to standard delimiters if JSON parsing fails

            # Try splitting by common delimiters: comma, semicolon, vertical bar, space
            delimiters = [',', ';', '|']
            for d in delimiters:
                if d in val_str:
                    return [code.strip() for code in val_str.split(d) if code.strip()]
            
            # Default fallback: split by whitespace if no delimiters are found
            return [code.strip() for code in val_str.split() if code.strip()]

        # For any other types (e.g. numeric codes, which is rare for ICD-10 but possible for ICD-9)
        return [str(val).strip()]

    def normalize_sex(self, val: Any) -> str:
        """
        Normalize sex input into 'M' or 'F' required by CMS models.
        
        Args:
            val: Raw sex/gender value.
            
        Returns:
            'M' or 'F'
        """
        if pd.isna(val) or val is None:
            raise ValueError("Sex/gender field is missing.")
            
        s = str(val).strip().upper()
        if not s:
            raise ValueError("Sex/gender field is empty.")
            
        if s.startswith('M') or s == '1':
            return 'M'
        elif s.startswith('F') or s == '2':
            return 'F'
        elif s.startswith('W'): # Woman
            return 'F'
        else:
            raise ValueError(f"Invalid sex/gender value: '{val}'. Must be M/F, Male/Female, or 1/2.")

    def process_row(self, row: pd.Series, id_col: str, age_col: str, sex_col: str, dx_col: Optional[str] = None, wide_dx_cols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Process a single patient row and calculate their HCC score.
        
        Args:
            row: A pandas Series representing one row/patient.
            id_col: Column name containing patient ID.
            age_col: Column name containing age.
            sex_col: Column name containing sex.
            dx_col: Column name containing diagnosis codes (narrow format).
            wide_dx_cols: List of column names containing diagnosis codes (wide format).
            
        Returns:
            A dictionary containing calculation results or error details.
        """
        patient_id = row[id_col] if id_col in row else "UNKNOWN"
        result_dict = {
            "patient_id": patient_id,
            "risk_score": 0.0,
            "risk_score_demographics": 0.0,
            "risk_score_hcc": 0.0,
            "hcc_list": "",
            "hcc_details_summary": "",
            "error_log": ""
        }

        try:
            # Validate age
            age_val = row[age_col]
            if pd.isna(age_val):
                raise ValueError("Age field is missing.")
            try:
                age = int(float(age_val))
            except Exception:
                raise ValueError(f"Invalid age value: '{age_val}'. Must be a number.")

            # Validate sex
            sex = self.normalize_sex(row[sex_col])

            # Gather diagnosis codes
            dx_codes = []
            if dx_col and dx_col in row:
                dx_codes.extend(self.parse_diagnosis_codes(row[dx_col]))
            
            if wide_dx_cols:
                for col in wide_dx_cols:
                    if col in row:
                        val = row[col]
                        if not pd.isna(val):
                            # In wide format, each column typically contains a single code
                            code = str(val).strip()
                            if code:
                                dx_codes.append(code)
            
            # Deduplicate diagnosis codes
            dx_codes = list(dict.fromkeys(dx_codes))

            # Run calculation
            res = self.processor.calculate_from_diagnosis(diagnosis_codes=dx_codes, age=age, sex=sex)

            # Map outputs
            result_dict["risk_score"] = float(res.risk_score)
            result_dict["risk_score_demographics"] = float(res.risk_score_demographics)
            result_dict["risk_score_hcc"] = float(res.risk_score_hcc)
            result_dict["hcc_list"] = ",".join(res.hcc_list)
            
            # Create a user-friendly summary of matched HCCs
            details = []
            for item in res.hcc_details:
                hcc = item.hcc
                label = item.label
                coeff = item.coefficient
                details.append(f"HCC {hcc} ({label}): +{coeff}")
            result_dict["hcc_details_summary"] = " | ".join(details)

        except Exception as e:
            result_dict["error_log"] = str(e)

        return result_dict

    def process_dataframe(self, df: pd.DataFrame, id_col: Optional[str] = None, age_col: Optional[str] = None, 
                          sex_col: Optional[str] = None, dx_col: Optional[str] = None, 
                          wide_dx_cols: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Process an entire DataFrame, calculate risk scores, and return a combined DataFrame.
        
        Args:
            df: Input patient DataFrame.
            id_col: Column name containing patient ID.
            age_col: Column name containing age.
            sex_col: Column name containing sex.
            dx_col: Column name containing diagnosis codes (narrow format).
            wide_dx_cols: List of column names containing diagnosis codes (wide format).
            
        Returns:
            DataFrame with original columns and new score columns appended.
        """
        # Column Auto-Detection
        detected = self.detect_columns(df)
        id_col = id_col or detected["id"]
        age_col = age_col or detected["age"]
        sex_col = sex_col or detected["sex"]
        dx_col = dx_col or detected["dx"]

        # Validate that we have the necessary column configurations
        if not age_col or not sex_col:
            raise ValueError(
                f"Demographics columns could not be fully identified. "
                f"Detected: Age Column = {age_col}, Sex Column = {sex_col}. "
                f"Please specify them explicitly."
            )
        if not dx_col and not wide_dx_cols:
            raise ValueError("No diagnosis column was specified or auto-detected.")

        # Print layout parameters to standard output
        print(f"Configured Columns:")
        print(f"  - Patient ID: {id_col}")
        print(f"  - Age Column: {age_col}")
        print(f"  - Sex Column: {sex_col}")
        if dx_col:
            print(f"  - Diagnoses Column: {dx_col}")
        if wide_dx_cols:
            print(f"  - Wide Diagnosis Columns: {wide_dx_cols}")

        results = []
        for idx, row in tqdm(df.iterrows(), total=len(df), desc="Calculating HCC Scores"):
            res = self.process_row(
                row, 
                id_col=id_col, 
                age_col=age_col, 
                sex_col=sex_col, 
                dx_col=dx_col, 
                wide_dx_cols=wide_dx_cols
            )
            results.append(res)

        res_df = pd.DataFrame(results)

        # Drop helper patient_id from output to avoid duplicate if we are joining
        res_df = res_df.drop(columns=["patient_id"])

        # Concatenate original columns with the results
        output_df = pd.concat([df.reset_index(drop=True), res_df.reset_index(drop=True)], axis=1)
        return output_df

    def process_file(self, input_path: str, output_path: str, chunksize: Optional[int] = None, 
                     id_col: Optional[str] = None, age_col: Optional[str] = None, 
                     sex_col: Optional[str] = None, dx_col: Optional[str] = None, 
                     wide_dx_cols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Process a CSV or Excel file, calculate risk scores, and write the output.
        Handles extremely large files using chunked processing when chunksize is specified.
        
        Args:
            input_path: Path to the input file (.csv, .xlsx).
            output_path: Path to save the scored output file.
            chunksize: Number of rows to read/write at a time (CSV only). Recommended for >50,000 rows.
            id_col: Column name containing patient ID.
            age_col: Column name containing age.
            sex_col: Column name containing sex.
            dx_col: Column name containing diagnosis codes (narrow format).
            wide_dx_cols: List of column names containing diagnosis codes (wide format).
            
        Returns:
            Dictionary containing run statistics and summaries.
        """
        start_time = time.time()
        file_ext = os.path.splitext(input_path)[1].lower()

        # Handle Excel file
        if file_ext in ('.xlsx', '.xls'):
            print(f"Reading Excel file: {input_path}")
            df = pd.read_excel(input_path)
            output_df = self.process_dataframe(
                df, id_col=id_col, age_col=age_col, sex_col=sex_col, 
                dx_col=dx_col, wide_dx_cols=wide_dx_cols
            )
            print(f"Writing Excel file: {output_path}")
            output_df.to_excel(output_path, index=False)
            
            run_time = time.time() - start_time
            stats = self._generate_run_stats(output_df, run_time)
            self._print_summary_report(stats)
            return stats

        # Handle CSV processing (Supports chunking)
        if chunksize:
            print(f"Processing CSV file in chunks of {chunksize}: {input_path}")
            reader = pd.read_csv(input_path, chunksize=chunksize)
            
            first_chunk = True
            hcc_counts = {}
            total_rows = 0
            successful_rows = 0
            error_count = 0
            sum_risk_score = 0.0

            # Estimate total file size/rows if possible for tqdm
            total_size_est = None
            try:
                with open(input_path, 'r', encoding='utf-8') as f:
                    total_size_est = sum(1 for _ in f) - 1 # exclude header
            except Exception:
                pass

            pbar = tqdm(total=total_size_est, desc="Processing Chunks")

            for chunk in reader:
                scored_chunk = self.process_dataframe(
                    chunk, id_col=id_col, age_col=age_col, sex_col=sex_col, 
                    dx_col=dx_col, wide_dx_cols=wide_dx_cols
                )
                
                # Write to file
                if first_chunk:
                    scored_chunk.to_csv(output_path, index=False, mode='w')
                    first_chunk = False
                else:
                    scored_chunk.to_csv(output_path, index=False, mode='a', header=False)
                
                # Accumulate statistics
                total_rows += len(scored_chunk)
                errors = scored_chunk["error_log"].str.len() > 0
                error_count += errors.sum()
                success = ~errors
                successful_rows += success.sum()
                
                if success.any():
                    sum_risk_score += scored_chunk.loc[success, "risk_score"].sum()
                
                # Accumulate HCC category frequencies
                for codes_str in scored_chunk.loc[success, "hcc_list"]:
                    if pd.notna(codes_str) and codes_str:
                        for hcc in str(codes_str).split(','):
                            hcc_counts[hcc] = hcc_counts.get(hcc, 0) + 1

                pbar.update(len(chunk))
            
            pbar.close()
            run_time = time.time() - start_time
            
            stats = {
                "total_rows": total_rows,
                "processed_successfully": successful_rows,
                "failed_rows": error_count,
                "average_risk_score": (sum_risk_score / successful_rows) if successful_rows > 0 else 0.0,
                "top_hccs": sorted(hcc_counts.items(), key=lambda x: x[1], reverse=True)[:10],
                "execution_time_seconds": run_time,
                "records_per_second": total_rows / run_time if run_time > 0 else 0.0
            }
            self._print_summary_report(stats)
            return stats
            
        else:
            # Read whole CSV
            print(f"Reading CSV file: {input_path}")
            df = pd.read_csv(input_path)
            output_df = self.process_dataframe(
                df, id_col=id_col, age_col=age_col, sex_col=sex_col, 
                dx_col=dx_col, wide_dx_cols=wide_dx_cols
            )
            print(f"Writing CSV file: {output_path}")
            output_df.to_csv(output_path, index=False)
            
            run_time = time.time() - start_time
            stats = self._generate_run_stats(output_df, run_time)
            self._print_summary_report(stats)
            return stats

    def _generate_run_stats(self, scored_df: pd.DataFrame, run_time: float) -> Dict[str, Any]:
        """Generate summary statistics from processed dataframe."""
        total_rows = len(scored_df)
        errors = scored_df["error_log"].str.len() > 0
        error_count = errors.sum()
        successful_rows = total_rows - error_count
        
        # Calculate average risk score of successful rows
        avg_score = 0.0
        if successful_rows > 0:
            avg_score = scored_df.loc[~errors, "risk_score"].mean()

        # Count HCC frequencies
        hcc_counts = {}
        for codes_str in scored_df.loc[~errors, "hcc_list"]:
            if pd.notna(codes_str) and codes_str:
                for hcc in str(codes_str).split(','):
                    hcc_counts[hcc] = hcc_counts.get(hcc, 0) + 1

        top_hccs = sorted(hcc_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_rows": total_rows,
            "processed_successfully": successful_rows,
            "failed_rows": error_count,
            "average_risk_score": float(avg_score),
            "top_hccs": top_hccs,
            "execution_time_seconds": run_time,
            "records_per_second": total_rows / run_time if run_time > 0 else 0.0
        }

    def _print_summary_report(self, stats: Dict[str, Any]):
        """Print a visually distinct CLI summary report."""
        print("\n" + "="*50)
        print("             HCC BATCH RUN SUMMARY")
        print("="*50)
        print(f"Total Rows Processed   : {stats['total_rows']:,}")
        print(f"Successful Calculations: {stats['processed_successfully']:,}")
        print(f"Failed Calculations    : {stats['failed_rows']:,}")
        print(f"Average Risk Score     : {stats['average_risk_score']:.4f}")
        print(f"Total Execution Time   : {stats['execution_time_seconds']:.2f} seconds")
        print(f"Throughput Rate        : {stats['records_per_second']:.1f} records/sec")
        print("-"*50)
        print("Top 10 Most Common HCC Categories:")
        if stats['top_hccs']:
            for rank, (hcc, count) in enumerate(stats['top_hccs'], 1):
                pct = (count / stats['processed_successfully']) * 100 if stats['processed_successfully'] > 0 else 0
                print(f"  {rank:2d}. HCC {hcc:4s} : {count:5,} patients ({pct:.2f}%)")
        else:
            print("  No HCCs mapped.")
        print("="*50 + "\n")

    @staticmethod
    def generate_mock_data(num_records: int = 10000, output_path: Optional[str] = None) -> pd.DataFrame:
        """
        Generate realistic mock patient dataset for performance and logic testing.
        
        Args:
            num_records: Number of patient rows to generate.
            output_path: If specified, saves the mock data as a CSV.
            
        Returns:
            DataFrame containing mock patient data.
        """
        print(f"Generating {num_records:,} mock patient records...")
        
        # Demographic distribution
        genders = ["M", "F", "Male", "Female", "1", "2"]
        gender_weights = [0.45, 0.45, 0.04, 0.04, 0.01, 0.01]

        # Common ICD-10 codes mapping to HCC categories
        hcc_codes = ["E11.9", "N18.3", "I50.9", "C34.90", "J44.9", "F32.9", "Z99.81", "E11.69", "I12.9", "N18.4"]
        non_hcc_codes = ["I10", "M17.9", "M81.0", "Z00.00", "R51.9", "K21.9", "H10.9", "J06.9"]
        all_codes = hcc_codes + non_hcc_codes
        
        # Weights to ensure realistic density
        code_probs = [0.08, 0.04, 0.05, 0.02, 0.06, 0.05, 0.02, 0.03, 0.02, 0.01] + [0.15, 0.12, 0.10, 0.15, 0.08, 0.12, 0.05, 0.10]
        
        data = []
        for i in range(1, num_records + 1):
            pat_id = f"PAT_{i:07d}"
            age = int(random.normalvariate(68, 12))
            age = max(1, min(100, age))
            
            sex = random.choices(genders, weights=gender_weights)[0]
            
            num_dx = random.choices([0, 1, 2, 3, 4, 5], weights=[0.1, 0.4, 0.25, 0.15, 0.07, 0.03])[0]
            
            chosen_dx = []
            if num_dx > 0:
                chosen_dx = random.choices(all_codes, weights=code_probs, k=num_dx)
                chosen_dx = list(set(chosen_dx))

            # Vary the delimiter formats for testing auto-detection parsing
            fmt = random.random()
            if not chosen_dx:
                dx_str = ""
            elif fmt < 0.05:
                dx_str = json.dumps(chosen_dx)
            elif fmt < 0.90:
                dx_str = ",".join(chosen_dx)
            elif fmt < 0.95:
                dx_str = ";".join(chosen_dx)
            else:
                dx_str = " ".join(chosen_dx)

            # Introduce minor errors (e.g. invalid age or missing sex) in 0.2% of rows
            if random.random() < 0.002:
                if random.random() < 0.5:
                    age = "INVALID"
                else:
                    sex = ""

            data.append({
                "PatientID": pat_id,
                "Age": age,
                "Gender": sex,
                "Diagnoses": dx_str
            })

        df = pd.DataFrame(data)

        if output_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            print(f"Saving mock data to: {output_path}")
            df.to_csv(output_path, index=False)
            print("Save complete.")

        return df

if __name__ == "__main__":
    # Run demo if executed directly
    print("Running HCCBatchProcessor Demo...")
    processor = HCCBatchProcessor()
    
    mock_input = "demo_mock_patients.csv"
    mock_output = "demo_mock_patients_scored.csv"
    
    HCCBatchProcessor.generate_mock_data(10000, output_path=mock_input)
    
    stats = processor.process_file(
        input_path=mock_input,
        output_path=mock_output,
        chunksize=2500
    )
    
    if os.path.exists(mock_input):
        os.remove(mock_input)
    if os.path.exists(mock_output):
        os.remove(mock_output)
    print("Demo execution finished.")
