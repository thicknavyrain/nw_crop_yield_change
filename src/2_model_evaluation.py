"""
MODEL OUTPUT EVALUATION SCRIPT

This script evaluates the output of the model by comparing it against a reference dataset.
It performs the following steps:

1. Loads the model output data and the reference data from CSV files.
2. Selects the relevant columns (corn, rice, soy, spring_wheat, and grasses for all 10 years).
3. Merges the dataframes on 'Country'.
4. Filters out rows with missing values or values greater than a specified threshold.
5. Calculates R² and Mean Absolute Difference (MAD) metrics for each country and crop.
6. Plots histograms of R² and MAD distributions for each crop.
7. Plots country-level R² and MAD values sorted by area.
8. Saves the evaluation metrics to a CSV file.
9. Saves the plots to the reports/figures directory.

AUTHOR: Your Name
DATE: YYYY-MM-DD
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import r2_score
import logging
import yaml
import os
import geopandas as gpd


def setup_logging():
    """
    Configures the logging settings.
    """
    os.makedirs('logs', exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/model_evaluation.log"),
            logging.StreamHandler()
        ]
    )


def load_config(config_path):
    """
    Loads the configuration from a YAML file.

    Parameters:
    - config_path (str): Path to the YAML configuration file.

    Returns:
    - dict: Configuration dictionary.
    """
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)


def load_data(reference_file_path, output_file_path):
    """
    Loads the reference and output data from CSV files.

    Parameters:
    - reference_file_path (str): Path to the reference data CSV file.
    - output_file_path (str): Path to the model output data CSV file.

    Returns:
    - tuple: (reference_df, output_df)
    """
    reference_df = pd.read_csv(reference_file_path)
    output_df = pd.read_csv(output_file_path)
    logging.info(f"Loaded reference data from {reference_file_path}")
    logging.info(f"Loaded model output data from {output_file_path}")
    return reference_df, output_df


def select_relevant_columns(df, selected_columns):
    """
    Selects the relevant columns from the dataframe.

    Parameters:
    - df (pandas.DataFrame): The dataframe to select columns from.
    - selected_columns (list): List of columns to select.

    Returns:
    - pandas.DataFrame: The dataframe with only the selected columns.
    """
    return df[selected_columns]


def merge_dataframes(reference_df, output_df, on_column='Country', suffixes=('_reference', '_output')):
    """
    Merges the reference and output dataframes on the specified column.

    Parameters:
    - reference_df (pandas.DataFrame): The reference dataframe.
    - output_df (pandas.DataFrame): The output dataframe.
    - on_column (str): The column name to merge on.
    - suffixes (tuple): Suffixes to use for overlapping columns.

    Returns:
    - pandas.DataFrame: The merged dataframe.
    """
    merged_df = pd.merge(reference_df, output_df, on=on_column, suffixes=suffixes)
    logging.info(f"Merged dataframes on column '{on_column}'")
    return merged_df


def filter_data(df, columns_to_check, max_value=100000):
    """
    Filters out rows where specified columns have values greater than max_value or NaN.

    Parameters:
    - df (pandas.DataFrame): The dataframe to filter.
    - columns_to_check (list): List of column base names to check (without suffixes).
    - max_value (float): The maximum acceptable value.

    Returns:
    - pandas.DataFrame: The filtered dataframe.
    """
    filtered_df = df.copy()
    for col in columns_to_check:
        filtered_df = filtered_df[
            (filtered_df[f'{col}_reference'] <= max_value) & (filtered_df[f'{col}_output'] <= max_value)
        ]
        filtered_df = filtered_df.dropna(subset=[f'{col}_reference', f'{col}_output'])
    logging.info(f"Filtered data to remove values greater than {max_value} and NaNs")
    return filtered_df


def calculate_metrics_for_country(row, crops, years):
    """
    Calculates R² and MAD metrics for a single country.
    """
    country = row['Country']
    metrics = {'Country': country}
    combined_reference = []
    combined_output = []
    for crop in crops:
        reference_values = row[[f'{crop}_year{year}_reference' for year in years]].values
        output_values = row[[f'{crop}_year{year}_output' for year in years]].values

        # Calculate R²
        try:
            r2 = r2_score(reference_values, output_values)
        except ValueError:
            logging.warning(f"Could not compute R² for {crop} in country {country}. Setting R² to NaN.")
            r2 = np.nan

        # Calculate MAD
        mad = np.mean(np.abs(reference_values - output_values))

        # Use title() for proper capitalization
        metrics[f'{crop.title()}_R2'] = r2
        metrics[f'{crop.title()}_MAD'] = mad

        combined_reference.extend(reference_values)
        combined_output.extend(output_values)

        # Handle special cases for specific crops and years
        if crop == 'soy':
            reference_values_6_10 = reference_values[5:]
            output_values_6_10 = output_values[5:]
            try:
                r2_6_10 = r2_score(reference_values_6_10, output_values_6_10)
            except ValueError:
                logging.warning(f"Could not compute R² for soy (years 6-10) in country {country}. Setting R² to NaN.")
                r2_6_10 = np.nan
            mad_6_10 = np.mean(np.abs(reference_values_6_10 - output_values_6_10))
            metrics['Soy_R2_6_10'] = r2_6_10
            metrics['Soy_MAD_6_10'] = mad_6_10

        if crop == 'spring_wheat':
            reference_values_5_10 = reference_values[4:]
            output_values_5_10 = output_values[4:]
            try:
                r2_5_10 = r2_score(reference_values_5_10, output_values_5_10)
            except ValueError:
                logging.warning(f"Could not compute R² for spring_wheat (years 5-10) in country {country}. Setting R² to NaN.")
                r2_5_10 = np.nan
            mad_5_10 = np.mean(np.abs(reference_values_5_10 - output_values_5_10))
            metrics['Spring_Wheat_R2_5_10'] = r2_5_10
            metrics['Spring_Wheat_MAD_5_10'] = mad_5_10

    # Calculate combined R² and MAD
    combined_reference = np.array(combined_reference)
    combined_output = np.array(combined_output)
    try:
        combined_r2 = r2_score(combined_reference, combined_output)
    except ValueError:
        logging.warning(f"Could not compute combined R² for country {country}. Setting R² to NaN.")
        combined_r2 = np.nan
    combined_mad = np.mean(np.abs(combined_reference - combined_output))

    metrics['Combined_R2'] = combined_r2
    metrics['Combined_MAD'] = combined_mad

    return metrics


def calculate_metrics(df, crops, years):
    """
    Calculates metrics for all countries.

    Parameters:
    - df (pandas.DataFrame): The dataframe containing the data.
    - crops (list): List of crop names.
    - years (list): List of years.

    Returns:
    - pandas.DataFrame: DataFrame containing the metrics for all countries.
    """
    results = []
    for index, row in df.iterrows():
        metrics = calculate_metrics_for_country(row, crops, years)
        results.append(metrics)
    results_df = pd.DataFrame(results)
    logging.info("Calculated metrics for all countries")
    return results_df


def plot_histograms(results_df, crops, output_filename):
    """
    Plots histograms of R² and MAD distributions for each crop.

    Parameters:
    - results_df (pandas.DataFrame): DataFrame containing the metrics.
    - crops (list): List of crop names.
    - output_filename (str): Filename to use for saving the plot.
    """
    fig, axs = plt.subplots(3, 5, figsize=(30, 18))
    bins = 25

    # Existing Corn, Rice, Soy, Spring Wheat, and Grasses plots
    for i, crop in enumerate(crops):
        crop_cap = crop.capitalize()
        # R² Histogram
        axs[0, i].hist(results_df[f'{crop_cap}_R2'].dropna(), bins=bins, color='skyblue', edgecolor='black')
        axs[0, i].axvline(results_df[f'{crop_cap}_R2'].mean(), color='red', linestyle='dashed', linewidth=1.5,
                          label=f"Mean: {results_df[f'{crop_cap}_R2'].mean():.2f}")
        axs[0, i].axvline(results_df[f'{crop_cap}_R2'].median(), color='blue', linestyle='dashed', linewidth=1.5,
                          label=f"Median: {results_df[f'{crop_cap}_R2'].median():.2f}")
        axs[0, i].set_title(f'{crop_cap} R² Distribution')
        axs[0, i].set_xlabel('R² Value')
        axs[0, i].set_ylabel('Frequency')
        axs[0, i].legend()

        # MAD Histogram
        axs[1, i].hist(results_df[f'{crop_cap}_MAD'].dropna(), bins=bins, color='lightgreen', edgecolor='black')
        axs[1, i].axvline(results_df[f'{crop_cap}_MAD'].mean(), color='red', linestyle='dashed', linewidth=1.5,
                          label=f"Mean: {results_df[f'{crop_cap}_MAD'].mean():.2f}")
        axs[1, i].axvline(results_df[f'{crop_cap}_MAD'].median(), color='blue', linestyle='dashed', linewidth=1.5,
                          label=f"Median: {results_df[f'{crop_cap}_MAD'].median():.2f}")
        axs[1, i].set_title(f'{crop_cap} MAD Distribution')
        axs[1, i].set_xlabel('MAD Value')
        axs[1, i].set_ylabel('Frequency')
        axs[1, i].legend()

    # Additional plots for Soy and Spring Wheat for specific years
    # Soy R² and MAD (years 6-10)
    axs[2, 0].hist(results_df['Soy_R2_6_10'].dropna(), bins=bins, color='lightcoral', edgecolor='black')
    axs[2, 0].axvline(results_df['Soy_R2_6_10'].mean(), color='red', linestyle='dashed', linewidth=1.5,
                      label=f"Mean: {results_df['Soy_R2_6_10'].mean():.2f}")
    axs[2, 0].axvline(results_df['Soy_R2_6_10'].median(), color='blue', linestyle='dashed', linewidth=1.5,
                      label=f"Median: {results_df['Soy_R2_6_10'].median():.2f}")
    axs[2, 0].set_title('Soy R² (Years 6-10) Distribution')
    axs[2, 0].set_xlabel('R² Value')
    axs[2, 0].set_ylabel('Frequency')
    axs[2, 0].legend()

    axs[2, 1].hist(results_df['Soy_MAD_6_10'].dropna(), bins=bins, color='lightcoral', edgecolor='black')
    axs[2, 1].axvline(results_df['Soy_MAD_6_10'].mean(), color='red', linestyle='dashed', linewidth=1.5,
                      label=f"Mean: {results_df['Soy_MAD_6_10'].mean():.2f}")
    axs[2, 1].axvline(results_df['Soy_MAD_6_10'].median(), color='blue', linestyle='dashed', linewidth=1.5,
                      label=f"Median: {results_df['Soy_MAD_6_10'].median():.2f}")
    axs[2, 1].set_title('Soy MAD (Years 6-10) Distribution')
    axs[2, 1].set_xlabel('MAD Value')
    axs[2, 1].set_ylabel('Frequency')
    axs[2, 1].legend()

    # Spring Wheat R² and MAD (years 5-10)
    axs[2, 2].hist(results_df['Spring_Wheat_R2_5_10'].dropna(), bins=bins, color='gold', edgecolor='black')
    axs[2, 2].axvline(results_df['Spring_Wheat_R2_5_10'].mean(), color='red', linestyle='dashed', linewidth=1.5,
                      label=f"Mean: {results_df['Spring_Wheat_R2_5_10'].mean():.2f}")
    axs[2, 2].axvline(results_df['Spring_Wheat_R2_5_10'].median(), color='blue', linestyle='dashed', linewidth=1.5,
                      label=f"Median: {results_df['Spring_Wheat_R2_5_10'].median():.2f}")
    axs[2, 2].set_title('Spring Wheat R² (Years 5-10) Distribution')
    axs[2, 2].set_xlabel('R² Value')
    axs[2, 2].set_ylabel('Frequency')
    axs[2, 2].legend()

    axs[2, 3].hist(results_df['Spring_Wheat_MAD_5_10'].dropna(), bins=bins, color='gold', edgecolor='black')
    axs[2, 3].axvline(results_df['Spring_Wheat_MAD_5_10'].mean(), color='red', linestyle='dashed', linewidth=1.5,
                      label=f"Mean: {results_df['Spring_Wheat_MAD_5_10'].mean():.2f}")
    axs[2, 3].axvline(results_df['Spring_Wheat_MAD_5_10'].median(), color='blue', linestyle='dashed', linewidth=1.5,
                      label=f"Median: {results_df['Spring_Wheat_MAD_5_10'].median():.2f}")
    axs[2, 3].set_title('Spring Wheat MAD (Years 5-10) Distribution')
    axs[2, 3].set_xlabel('MAD Value')
    axs[2, 3].set_ylabel('Frequency')
    axs[2, 3].legend()

    plt.tight_layout()
    # Save plot to reports/figures
    figures_dir = os.path.join('reports', 'figures')
    os.makedirs(figures_dir, exist_ok=True)
    plot_filepath = os.path.join(figures_dir, output_filename)
    plt.savefig(plot_filepath)
    logging.info(f"Saved plot to {plot_filepath}")
    plt.close()


def plot_country_level_metrics(results_df, config):
    """
    Plots R² and MAD values for each country, sorted by area.
    """
    # Load shapefile
    shapefile_path = config['shapefile_path']
    gdf = gpd.read_file(shapefile_path)
    logging.info(f"Loaded shapefile from {shapefile_path}")

    # Read country mapping from config
    country_mapping = config['country_mapping']

    # Apply country mapping to GeoDataFrame
    gdf['COUNTRY'] = gdf['COUNTRY'].replace(country_mapping)

    # Reproject GeoDataFrame to a projected CRS
    gdf = gdf.to_crs(epsg=6933)  # Use an appropriate EPSG code for your area calculations

    # Calculate area of each country
    gdf['Area'] = gdf['geometry'].area
    logging.info("Calculated country areas after reprojecting")

    # Merge results_df with gdf on 'Country' and 'COUNTRY'
    merged_df = pd.merge(results_df, gdf, left_on='Country', right_on='COUNTRY', how='inner')
    logging.info("Merged evaluation metrics with GeoDataFrame")

    # Sort by area in descending order
    merged_df_sorted = merged_df.sort_values(by='Area', ascending=False)

    # Exclude Kyrgyzstan if necessary
    merged_df_sorted = merged_df_sorted[merged_df_sorted['Country'] != 'Kyrgyzstan']

    # Plot R² values for each country
    crops = ['Corn', 'Rice', 'Soy', 'Spring_Wheat', 'Grasses', 'Combined']
    colors = {
        'Corn': 'tab:blue',
        'Rice': 'tab:green',
        'Soy': 'tab:red',
        'Spring_Wheat': 'tab:orange',
        'Grasses': 'tab:purple',
        'Combined': 'tab:pink'
    }
    markers = {
        'R2': 'o',
        'R2_special': 's',
        'MAD': 'x',
        'MAD_special': '^'
    }

    # Plotting R² values
    fig, ax = plt.subplots(figsize=(10, 25))
    for crop in crops:
        ax.scatter(merged_df_sorted[f'{crop}_R2'], merged_df_sorted['Country'],
                   label=f'{crop} R²', marker=markers['R2'], color=colors[crop])

    # Special cases for Soy and Spring Wheat
    ax.scatter(merged_df_sorted['Soy_R2_6_10'], merged_df_sorted['Country'],
               label='Soy R² (Years 6-10)', marker=markers['R2_special'], color=colors['Soy'])
    ax.scatter(merged_df_sorted['Spring_Wheat_R2_5_10'], merged_df_sorted['Country'],
               label='Spring Wheat R² (Years 5-10)', marker=markers['R2_special'], color=colors['Spring_Wheat'])

    ax.set_xlabel('R² Value')
    ax.set_ylabel('Country (Sorted by Area)')
    ax.set_title('R² Values for Crops and Combined for Each Country (Sorted by Area)')
    ax.legend()
    ax.grid(True)
    plt.tight_layout()

    # Save plot
    figures_dir = os.path.join('reports', 'figures')
    os.makedirs(figures_dir, exist_ok=True)
    plot_filepath = os.path.join(figures_dir, 'country_r2_values.png')
    plt.savefig(plot_filepath)
    logging.info(f"Saved country R² plot to {plot_filepath}")
    plt.close()

    # Plot R² values with x-axis range set between 0 and 1.1
    fig, ax = plt.subplots(figsize=(10, 25))
    for crop in crops:
        ax.scatter(merged_df_sorted[f'{crop}_R2'], merged_df_sorted['Country'],
                   label=f'{crop} R²', marker=markers['R2'], color=colors[crop])

    # Special cases for Soy and Spring Wheat
    ax.scatter(merged_df_sorted['Soy_R2_6_10'], merged_df_sorted['Country'],
               label='Soy R² (Years 6-10)', marker=markers['R2_special'], color=colors['Soy'])
    ax.scatter(merged_df_sorted['Spring_Wheat_R2_5_10'], merged_df_sorted['Country'],
               label='Spring Wheat R² (Years 5-10)', marker=markers['R2_special'], color=colors['Spring_Wheat'])

    ax.set_xlim(0, 1.1)
    ax.set_xlabel('R² Value')
    ax.set_ylabel('Country (Sorted by Area)')
    ax.set_title('R² Values for Crops and Combined for Each Country (R² Range 0-1.1)')
    ax.legend()
    ax.grid(True)
    plt.tight_layout()

    plot_filepath = os.path.join(figures_dir, 'country_r2_values_zoomed.png')
    plt.savefig(plot_filepath)
    logging.info(f"Saved country R² zoomed plot to {plot_filepath}")
    plt.close()

    # Plot MAD values
    fig, ax = plt.subplots(figsize=(10, 25))
    for crop in crops:
        ax.scatter(merged_df_sorted[f'{crop}_MAD'], merged_df_sorted['Country'],
                   label=f'{crop} MAD', marker=markers['MAD'], color=colors[crop])

    # Special cases for Soy and Spring Wheat
    ax.scatter(merged_df_sorted['Soy_MAD_6_10'], merged_df_sorted['Country'],
               label='Soy MAD (Years 6-10)', marker=markers['MAD_special'], color=colors['Soy'])
    ax.scatter(merged_df_sorted['Spring_Wheat_MAD_5_10'], merged_df_sorted['Country'],
               label='Spring Wheat MAD (Years 5-10)', marker=markers['MAD_special'], color=colors['Spring_Wheat'])

    ax.set_xlabel('MAD Value')
    ax.set_ylabel('Country (Sorted by Area)')
    ax.set_title('MAD Values for Crops and Combined for Each Country (Sorted by Area)')
    ax.set_xscale('log')
    ax.legend()
    ax.grid(True)
    plt.tight_layout()

    plot_filepath = os.path.join(figures_dir, 'country_mad_values.png')
    plt.savefig(plot_filepath)
    logging.info(f"Saved country MAD plot to {plot_filepath}")
    plt.close()


def main():
    """
    Main function to perform model evaluation.
    """
    setup_logging()

    # Load configuration
    config = load_config('config/config.yaml')

    # Define file paths
    reference_file_path = config['reference_file_path']
    output_file_path = config['output_file_path']

    # Define crops and years
    crops = ['corn', 'rice', 'soy', 'spring_wheat', 'grasses']
    years = list(range(1, 11))  # Years 1 to 10

    # Load data
    reference_df, output_df = load_data(reference_file_path, output_file_path)

    # Select relevant columns
    selected_columns = ['Country']
    for crop in crops:
        selected_columns.extend([f'{crop}_year{year}' for year in years])
    reference_df = select_relevant_columns(reference_df, selected_columns)
    output_df = select_relevant_columns(output_df, selected_columns)

    # Merge dataframes
    merged_df = merge_dataframes(reference_df, output_df, on_column='Country', suffixes=('_reference', '_output'))

    # Filter data
    columns_to_check = []
    for crop in crops:
        for year in years:
            columns_to_check.append(f'{crop}_year{year}')
    filtered_df = filter_data(merged_df, columns_to_check, max_value=100000)

    # Exclude specific countries if necessary
    # filtered_df = filtered_df[~filtered_df['Country'].isin(['Kyrgyzstan'])]

    # Calculate metrics
    results_df = calculate_metrics(filtered_df, crops, years)

    # Save metrics to CSV
    reports_dir = 'reports'
    os.makedirs(reports_dir, exist_ok=True)
    metrics_filename = os.path.join(reports_dir, 'model_evaluation_metrics.csv')
    results_df.to_csv(metrics_filename, index=False)
    logging.info(f"Saved evaluation metrics to {metrics_filename}")

    # Plot histograms
    output_filename = os.path.basename(output_file_path)[:-4] + '_evaluation.png'
    plot_histograms(results_df, crops, output_filename)

    # Plot country-level metrics
    plot_country_level_metrics(results_df, config)


if __name__ == '__main__':
    main()