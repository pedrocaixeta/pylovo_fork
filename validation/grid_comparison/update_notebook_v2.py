
import json
from pathlib import Path

nb_path = Path("/home/breveron/git/github/pylovo/validation/grid_comparison_notebook.ipynb")

if not nb_path.exists():
    print(f"Error: {nb_path} does not exist.")
    exit(1)

with open(nb_path, 'r') as f:
    nb = json.load(f)

cells = nb['cells']

# 1. Clean up "interactive_histogram" to remove the PDF call I added previously
for cell in cells:
    source = cell.get('source', [])
    source_str = "".join(source)
    if "def interactive_histogram(metric):" in source_str and "fig_pdf =" in source_str:
        print("Cleaning up interactive_histogram cell...")
        new_source = [
            "\n",
            "def interactive_histogram(metric):\n",
            "    fig = plotting.plot_comparison_histogram_plotly(df_all, metric, title=f\"Histogram of {metric}\")\n",
            "    fig.show()\n",
            "\n",
            "widgets.interact(interactive_histogram, metric=widgets.Dropdown(options=metrics, value='cable_length_km', description='Metric:'));\n"
        ]
        cell['source'] = new_source

# 2. Add New Section for PDF Comparison
# Find where to insert: Before "## Statistical Comparison (KS-Test)"
insert_idx = -1
for i, cell in enumerate(cells):
    source = cell.get('source', [])
    source_str = "".join(source)
    if "## Statistical Comparison (KS-Test)" in source_str:
        insert_idx = i
        break

if insert_idx != -1:
    print(f"Inserting PDF section before index {insert_idx}")
    
    markdown_cell = {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "\n",
            "## Interactive PDF Comparison\n",
            "Compare Probability Density Functions (PDFs) estimated via KDE to see shape differences more clearly without binning artifacts.\n"
        ]
    }
    
    code_cell = {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "\n",
            "def interactive_pdf(metric):\n",
            "    fig = plotting.plot_comparison_pdf_plotly(df_all, metric, title=f\"PDF Comparison: {metric}\")\n",
            "    fig.show()\n",
            "\n",
            "widgets.interact(interactive_pdf, metric=widgets.Dropdown(options=metrics, value='cable_length_km', description='Metric:'));\n"
        ]
    }
    
    # Check if we already inserted it to avoid duplicates (idempotency)
    # Check previous cell
    prev_cell_source = "".join(cells[insert_idx-1]['source']) if insert_idx > 0 else ""
    if "plot_comparison_pdf_plotly" not in prev_cell_source: # Only insert if not present
         cells.insert(insert_idx, code_cell)
         cells.insert(insert_idx, markdown_cell)
    else:
         print("PDF section seems to already exist. Skipping insertion.")

else:
    print("Could not find insertion point.")

with open(nb_path, 'w') as f:
    json.dump(nb, f, indent=1)

print("Notebook updated v2.")
