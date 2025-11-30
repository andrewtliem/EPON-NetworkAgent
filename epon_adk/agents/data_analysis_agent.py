import json
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for thread safety
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import uuid
import sys
import io
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional
from google.adk.agents import LlmAgent

# Ensure charts directory exists
CHARTS_DIR = Path(__file__).parent.parent / "web" / "static" / "charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

def execute_python_analysis(code: str, data_json: str) -> str:
    """
    Executes Python code to analyze or visualize the provided telemetry data.
    
    The code has access to a pandas DataFrame named `df` containing the data.
    The code should save any plots to the directory `CHARTS_DIR` (available in context).
    
    Args:
        code: The Python code to execute.
        data_json: The telemetry data as a JSON string.
        
    Returns:
        String containing stdout, stderr, and any generated file paths.
    """
    # 1. Prepare Data
    try:
        data = json.loads(data_json)
        # Flatten if needed (handle grouped by ONU)
        if isinstance(data, dict):
            flat_data = []
            for key, items in data.items():
                if isinstance(items, list):
                    flat_data.extend(items)
            data = flat_data
            
        # Flatten nested dictionaries for DataFrame
        flat_rows = []
        for item in data:
            row = {}
            def flatten(x, name=''):
                if type(x) is dict:
                    for a in x:
                        flatten(x[a], name + a + '.')
                else:
                    row[name[:-1]] = x
            flatten(item)
            flat_rows.append(row)
            
        df = pd.DataFrame(flat_rows)
        
    except Exception as e:
        return f"Data preparation failed: {str(e)}"

    # 2. Prepare Execution Context
    # Redirect stdout to capture print statements
    old_stdout = sys.stdout
    redirected_output = io.StringIO()
    sys.stdout = redirected_output
    
    # Define the local scope for the code
    local_scope = {
        "df": df,
        "pd": pd,
        "plt": plt,
        "sns": sns,
        "CHARTS_DIR": CHARTS_DIR,
        "uuid": uuid,
    }
    
    # 3. Execute Code
    try:
        exec(code, {}, local_scope)
        output = redirected_output.getvalue()
        return f"Execution Successful.\nOutput:\n{output}"
    except Exception as e:
        return f"Execution Failed:\n{traceback.format_exc()}"
    finally:
        sys.stdout = old_stdout
        plt.close('all') # Cleanup figures


data_analysis_agent = LlmAgent(
    name="data_analysis_agent",
    model="gemini-2.5-flash",
    description="Performs dynamic data analysis and visualization using Python code execution.",
    instruction=(
    "You are the Data Analysis Agent with Code Execution capabilities.\n"
    "Your goal is to analyze EPON telemetry data or create visualizations.\n\n"

    "You have access to a tool `execute_python_analysis` which runs Python code.\n"
    "The code environment has a pandas DataFrame `df` pre-loaded with the data.\n"
    "Available libraries: `pandas` (pd), `matplotlib.pyplot` (plt), `seaborn` (sns).\n"
    "A Path object named CHARTS_DIR is available for saving charts.\n\n"

    "IMPORTANT RULES WHEN CREATING CHARTS (MUST FOLLOW EXACTLY):\n"
    "1. Always begin a new plot with plt.figure().\n"
    "2. Always generate a filename using:\n"
    "       filename = f\"{uuid.uuid4()}.png\"\n"
    "3. Always construct the full file path using EXACTLY:\n"
    "       filepath = CHARTS_DIR / filename\n"
    "4. Always save the chart using EXACTLY:\n"
    "       plt.savefig(filepath)\n"
    "5. NEVER use plt.savefig(\"something.png\"). NEVER save to the working directory.\n"
    "6. NEVER create paths manually. Always use CHARTS_DIR / filename.\n"
    "7. After saving, print ONLY the public static path:\n"
    "       /static/charts/<filename>\n\n"

    "When performing analysis without charts, simply print text output.\n"
    "Return the result (text or chart path) to the user."
    ),
    tools=[execute_python_analysis],
    output_key="visualization_path"
)

