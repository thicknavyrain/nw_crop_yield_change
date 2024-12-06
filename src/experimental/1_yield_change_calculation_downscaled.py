"""
CROP AND GRASS YIELD PERCENTAGE CHANGE CALCULATION SCRIPT

This code processes crop and grass yield data from NetCDF datasets, calculates percentage changes in yields
for various crops and grasses across countries for the first 10 years post-nuclear winter, and outputs the 
results to CSV files.
It performs the following steps:

1. Aligns longitudes in the datasets from [0, 360] to [-180, 180] for spatial merging.
2. Ensures consistent coordinate reference systems (CRS) across datasets.
3. Assigns CRS and reprojects yield data to equal-area projection before aggregation.
4. Aggregates rainfed and irrigated yields for specified crops.
5. Aggregates yields for grasses (C3grass and C4grass).
6. Downscales the yield data to a finer resolution.
7. Clips yield data to country geometries provided in a shapefile.
8. Calculates total yield per country and percentage changes compared to control datasets.
9. Averages percentage changes across multiple control datasets.
10. Applies country name mappings for consistency.
11. Outputs the results to CSV files sorted alphabetically by country name.

AUTHOR: Ricky Nathvani
DATE: YYYY-MM-DD
"""

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from tqdm import tqdm
import logging
import yaml
import rioxarray
from rioxarray.exceptions import NoDataInBounds
from rasterio.enums import Resampling
from shapely.geometry import mapping


def setup_logging():
    """
    Configures the logging settings.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/yield_processing.log"),
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


def fix_longitude(ds):
    """
    Correct longitude from [0, 360] to [-180, 180] and sort the dataset.

    Parameters:
    - ds (xarray.Dataset): The dataset with longitude coordinates to be corrected.

    Returns:
    - xarray.Dataset: The dataset with corrected and sorted longitude coordinates.
    """
    ds = ds.assign_coords(lon=(((ds['lon'] + 180) % 360) - 180)).sortby('lon')
    return ds


def assign_crs(data_array, epsg_code=4326):
    """
    Assign a coordinate reference system (CRS) to a DataArray after validating latitude values.

    Parameters:
    - data_array (xarray.DataArray): The DataArray to assign CRS to.
    - epsg_code (int): The EPSG code for the coordinate reference system (default is 4326).

    Returns:
    - xarray.DataArray: The DataArray with assigned CRS.
    """
    # Check if 'lat' coordinate exists
    if 'lat' not in data_array.coords:
        logging.error("DataArray does not contain 'lat' coordinate.")
        raise KeyError("Missing 'lat' coordinate.")

    # Extract latitude values
    lat = data_array['lat']
    min_lat = lat.min().item()
    max_lat = lat.max().item()
    logging.info(f"Latitude range: min={min_lat}, max={max_lat}")

    # Validate latitude values, including exact poles
    if min_lat <= -90 or max_lat >= 90:
        logging.warning(f"Invalid latitude values detected: min={min_lat}, max={max_lat}. Clipping to valid range.")
        # Clip latitude values to the valid range, excluding exact poles
        data_array = data_array.where((lat > -90) & (lat < 90), drop=True)
        lat = data_array['lat']
        min_lat = lat.min().item()
        max_lat = lat.max().item()
        logging.info(f"Latitude range after clipping: min={min_lat}, max={max_lat}")

        # Re-check latitude after clipping
        if min_lat <= -90 or max_lat >= 90:
            logging.error("Clipping did not resolve invalid latitude values.")
            raise ValueError("Data contains invalid latitude values even after clipping.")

    # Verify spatial dimensions
    dims = data_array.dims
    coords = list(data_array.coords)
    logging.info(f"DataArray dimensions: {dims}")
    logging.info(f"DataArray coordinates: {coords}")

    # Ensure 'lat' and 'lon' are dimensions
    if 'lat' not in dims or 'lon' not in dims:
        logging.error("'lat' and/or 'lon' are not dimensions of the DataArray.")
        raise ValueError("'lat' and/or 'lon' are not dimensions of the DataArray.")

    # Proceed with CRS assignment
    try:
        # Log existing CRS if available
        existing_crs = data_array.rio.crs
        if existing_crs:
            logging.info(f"Existing CRS: {existing_crs}")
        else:
            logging.info(f"No existing CRS found. Assigning EPSG:{epsg_code} as the source CRS.")

        data_array = (
            data_array.rio.set_spatial_dims(x_dim='lon', y_dim='lat')
            .rio.write_crs(f"EPSG:{epsg_code}")  # Assigning the CRS
        )
        logging.info(f"Assigned CRS EPSG:{epsg_code} to data array.")
    except Exception as e:
        logging.error(f"Assigning CRS failed: {e}")
        raise e

    return data_array


def aggregate_yields(ds, rain_idx, irr_idx, year):
    """
    Extract and sum rainfed and irrigated yields from a dataset.

    Parameters:
    - ds (xarray.Dataset): The dataset containing yield data.
    - rain_idx (int): The index of the rainfed crop in the 'crops' dimension.
    - irr_idx (int): The index of the irrigated crop in the 'crops' dimension.
    - year (int): The year index to extract.

    Returns:
    - xarray.DataArray: The total yield (rainfed + irrigated) for the crop for the specified year.
    """
    # Extract rainfed and irrigated yields for the given year
    rain_yield = ds['yield'].isel(crops=rain_idx, time=year).fillna(0).astype(np.float32)
    irr_yield = ds['yield'].isel(crops=irr_idx, time=year).fillna(0).astype(np.float32)

    # Sum the yields
    total_yield = (rain_yield + irr_yield).astype(np.float32)
    return total_yield


def aggregate_grass_yields(ds, year):
    """
    Sum the yields of C3grass and C4grass across the 'grass' dimension.

    Parameters:
    - ds (xarray.Dataset): The dataset containing grass yield data.
    - year (int): The year index to extract.

    Returns:
    - xarray.DataArray: The total yield for grasses for the specified year.
    """
    grass_yields = []
    for grass_idx in range(len(ds['grass'])):
        # Extract yield for this grass type and the given year
        grass_yield = ds['yield'].isel(grass=grass_idx, time=year).fillna(0).astype(np.float32)
        grass_yields.append(grass_yield)
    # Sum the yields
    total_yield = sum(grass_yields)
    return total_yield


def downscale_data(data_array, factor=10):
    """
    Downscale the data array by a given factor.

    Parameters:
    - data_array (xarray.DataArray): The data array to downscale.
    - factor (int): The downscaling factor.

    Returns:
    - xarray.DataArray: The downscaled data array.
    """
    # Assign CRS if not assigned
    if not data_array.rio.crs:
        logging.info("CRS not found in data array. Assigning EPSG:4326.")
        data_array = data_array.rio.set_spatial_dims(x_dim='lon', y_dim='lat').rio.write_crs("EPSG:4326")

    # Get current resolution
    lat = data_array['lat'].values
    lon = data_array['lon'].values

    if len(lat) < 2 or len(lon) < 2:
        logging.warning("Not enough data points to calculate resolution for downscaling.")
        return data_array

    delta_lat = np.abs(lat[1] - lat[0])
    delta_lon = np.abs(lon[1] - lon[0])

    logging.info(f"Original resolution: {delta_lat} degrees latitude, {delta_lon} degrees longitude")

    # Calculate new resolution
    new_delta_lat = delta_lat / factor
    new_delta_lon = delta_lon / factor

    logging.info(f"New resolution: {new_delta_lat} degrees latitude, {new_delta_lon} degrees longitude")

    # Downscale the raster data
    downscaled = data_array.rio.reproject(
        dst_crs="EPSG:4326",
        resolution=(new_delta_lon, new_delta_lat),
        resampling=Resampling.nearest
    )

    # Divide the pixel values by factor squared
    downscaled = downscaled / (factor * factor)  # Dividing by 10000

    return downscaled


def clip_yield_to_country(yield_data, country_geometry, epsg_code):
    """
    Clip yield data to a country geometry.

    Parameters:
    - yield_data (xarray.DataArray): The yield data to be clipped.
    - country_geometry (list): A list containing the country's geometry.
    - epsg_code (int): The EPSG code for the coordinate reference system.

    Returns:
    - xarray.DataArray: The clipped yield data for the country.
    """
    try:
        clipped_yield = yield_data.rio.clip(
            country_geometry, crs=f"EPSG:{epsg_code}", drop=False, all_touched=True
        )
    except NoDataInBounds:
        logging.warning("No data within the bounds of the country geometry.")
        clipped_yield = yield_data.copy(deep=True) * 0  # Create an array of zeros
    return clipped_yield


def calculate_percentage_change(total_yield_value, reference_yield_value):
    """
    Calculate the percentage change between total yield and reference yield.

    Parameters:
    - total_yield_value (float): The total yield value for the target dataset.
    - reference_yield_value (float): The total yield value for the reference dataset.

    Returns:
    - float: The percentage change in yield.
    """
    if reference_yield_value > 0:
        percentage_change = 100 * (total_yield_value - reference_yield_value) / reference_yield_value
    else:
        percentage_change = np.nan
    return percentage_change


def process_yields(ds, control_datasets, gdf, aggregation_info, names_list, years, epsg_code, country_mapping):
    """
    Unified function to process yield data for both crops and grasses.
    """
    # Initialize a dictionary to store percentage changes for each country
    percentage_changes = {}

    # Determine if we're processing crops or grasses
    if aggregation_info:
        # Processing crops
        groups = aggregation_info.items()
    else:
        # Processing grasses; create a single group
        groups = [('grasses', None)]

    # Loop over each group
    for group_name, sub_components in tqdm(groups, desc='Processing groups'):
        # Iterate over each year
        for year in tqdm(range(years)):
            logging.info(f"Processing group {group_name}, year {year + 1}")
            # Aggregate yields based on whether we're processing crops or grasses
            if sub_components:
                # For crops, find indices for rainfed and irrigated components
                rain_idx = names_list.index(sub_components[0])
                irr_idx = names_list.index(sub_components[1])
                # Aggregate yields for target dataset
                total_yield_year = aggregate_yields(ds, rain_idx, irr_idx, year)
            else:
                # For grasses, aggregate across the 'grass' dimension
                total_yield_year = aggregate_grass_yields(ds, year)

            # Assign CRS to total yield data (EPSG:4326)
            total_yield_year = assign_crs(total_yield_year, epsg_code=4326)

            # Downscale the total yield data
            total_yield_year = downscale_data(total_yield_year)

            # Reproject to target EPSG code
            total_yield_year = total_yield_year.rio.reproject(f"EPSG:{epsg_code}")

            # Initialize a list to store the percentage changes for each reference dataset
            year_percentage_changes = []

            # For each control dataset
            for ctrl_ds in tqdm(control_datasets):
                # Aggregate yields for control dataset
                if sub_components:
                    reference_yield_year = aggregate_yields(ctrl_ds, rain_idx, irr_idx, year)
                else:
                    reference_yield_year = aggregate_grass_yields(ctrl_ds, year)

                # Assign CRS to reference yield data (EPSG:4326)
                reference_yield_year = assign_crs(reference_yield_year, epsg_code=4326)

                # Downscale the reference yield data
                reference_yield_year = downscale_data(reference_yield_year)

                # Reproject to target EPSG code
                reference_yield_year = reference_yield_year.rio.reproject(f"EPSG:{epsg_code}")

                # Iterate over each country polygon in the GeoDataFrame
                for idx, country in gdf.iterrows():
                    country_name = country['COUNTRY']
                    country_iso = country['ISO']

                    # Apply country name mapping if necessary
                    country_name = country_mapping.get(country_name, country_name)
                    country_geometry = [mapping(country['geometry'])]

                    try:
                        # Clip the yield data to the country geometry
                        clipped_total_yield = clip_yield_to_country(
                            total_yield_year, country_geometry, epsg_code
                        )
                        clipped_reference_yield = clip_yield_to_country(
                            reference_yield_year, country_geometry, epsg_code
                        )

                        # Calculate the total yield for the country
                        total_yield_value = clipped_total_yield.sum(skipna=True).item()
                        reference_yield_value = clipped_reference_yield.sum(skipna=True).item()

                        # Calculate the percentage change
                        percentage_change = calculate_percentage_change(
                            total_yield_value, reference_yield_value
                        )

                        # Append the percentage change to the list for this year
                        year_percentage_changes.append({
                            'country': country_name,
                            'iso': country_iso,
                            'percentage_change': percentage_change
                        })

                    except Exception as e:
                        logging.error(f"Could not process {country_name} for year {year + 1} and group {group_name}: {e}")

            # Now average the percentage changes across all reference datasets
            if year_percentage_changes:
                year_df = pd.DataFrame(year_percentage_changes)

                # Average the percentage changes for each country
                average_changes = year_df.groupby(['country', 'iso'])['percentage_change'].mean().reset_index()

                # Store the results
                for _, row in average_changes.iterrows():
                    country_name = row['country']
                    country_iso = row['iso']
                    avg_percentage_change = row['percentage_change']

                    # Initialize the dictionary entry for the country if it doesn't exist
                    if country_name not in percentage_changes:
                        percentage_changes[country_name] = {
                            'ISO3 Country Code': country_iso,
                            'Country': country_name
                        }

                    # Adjust the group name for special cases
                    if group_name == "Wheat":
                        group_col_name = "spring_wheat"
                    else:
                        group_col_name = group_name.lower()

                    # Store the average percentage change
                    percentage_changes[country_name][f'{group_col_name}_year{year + 1}'] = avg_percentage_change

    result_df = pd.DataFrame.from_dict(percentage_changes, orient='index').reset_index(drop=True)

    # Sort by country name
    result_df = result_df.sort_values(by='Country').reset_index(drop=True)

    return result_df


def process_scenario(scenario_name, crop_file_paths, grass_file_paths, control_crop_files, control_grass_files, gdf, crop_aggregation, country_mapping, EPSG=6933, years=10):
    """
    Process a single scenario and output the results to CSV files.

    Parameters:
    - scenario_name (str): Name of the scenario (e.g., '150Tg', '5Tg', etc.).
    - crop_file_paths (list): List of file paths for the crop datasets for this scenario.
    - grass_file_paths (list): List of file paths for the grass datasets for this scenario.
    - control_crop_files (list): List of control crop dataset file paths.
    - control_grass_files (list): List of control grass dataset file paths.
    - gdf (geopandas.GeoDataFrame): GeoDataFrame containing country geometries.
    - crop_aggregation (dict): Dictionary mapping main crops to their rainfed and irrigated components.
    - country_mapping (dict): Dictionary mapping old country names to new ones.
    - EPSG (int): The EPSG code for the coordinate reference system.
    - years (int): Number of years to process.

    Returns:
    - None
    """
    # Load control datasets
    control_datasets = [fix_longitude(xr.open_dataset(fp)) for fp in control_crop_files]
    grass_control_datasets = [fix_longitude(xr.open_dataset(fp)) for fp in control_grass_files]

    # Lists to store results
    combined_results = []

    # Process each pair of crop and grass files
    for idx, (crop_file, grass_file) in enumerate(zip(crop_file_paths, grass_file_paths)):
        ds_crop = fix_longitude(xr.open_dataset(crop_file))
        ds_grass = fix_longitude(xr.open_dataset(grass_file))
        crop_names = ds_crop['crops'].attrs['long_name'].split(',')
        grass_names = ds_grass['grass'].attrs['long_name'].split(', ')

        # Process crops
        if 'yield' in ds_crop.data_vars and all('yield' in ctrl_ds.data_vars for ctrl_ds in control_datasets):
            result_crop_df = process_yields(
                ds=ds_crop,
                control_datasets=control_datasets,
                gdf=gdf,
                aggregation_info=crop_aggregation,
                names_list=crop_names,
                years=years,
                epsg_code=EPSG,
                country_mapping=country_mapping
            )
        else:
            logging.warning(f"Crop dataset does not contain a 'yield' variable for scenario {scenario_name}.")
            continue

        # Process grasses
        if 'yield' in ds_grass.data_vars and all('yield' in ctrl_ds.data_vars for ctrl_ds in grass_control_datasets):
            result_grass_df = process_yields(
                ds=ds_grass,
                control_datasets=grass_control_datasets,
                gdf=gdf,
                aggregation_info=None,  # No aggregation info for grasses
                names_list=grass_names,
                years=years,
                epsg_code=EPSG,
                country_mapping=country_mapping
            )
        else:
            logging.warning(f"Grass dataset does not contain a 'yield' variable for scenario {scenario_name}.")
            continue

        # Merge crop and grass results
        final_df = pd.merge(result_crop_df, result_grass_df, on=['ISO3 Country Code', 'Country'], how='outer')
        final_df = final_df.sort_values(by='Country').reset_index(drop=True)
        output_filename = f'data/processed/output_{scenario_name}_crops_and_grasses_{idx + 1}.csv'
        final_df.to_csv(output_filename, index=False)
        logging.info(f"Saved combined results to {output_filename}")

        # Store the final_df
        combined_results.append(final_df)

    # For scenarios with multiple files (e.g., 5Tg), compute aggregated results
    if len(combined_results) > 1:
        # Average combined results
        avg_combined_df = pd.concat(combined_results).groupby(['ISO3 Country Code', 'Country']).mean().reset_index()
        # Save the aggregated result
        output_filename = f'data/processed/output_{scenario_name}_crops_and_grasses_aggregated.csv'
        avg_combined_df.to_csv(output_filename, index=False)
        logging.info(f"Saved aggregated results to {output_filename}")


def main():
    """
    Main function to execute the crop and grass yield percentage change calculation for multiple scenarios.
    """
    setup_logging()

    # Load configuration
    config = load_config('config/config.yaml')

    # Control files (common across nuclear winter soot level scenarios)
    control_crop_files = config['control_crop_files']
    control_grass_files = config['control_grass_files']

    # Scenarios to process
    scenarios = config['scenarios']

    # Path to shapefile with the country boundaries
    shapefile_path = config['shapefile_path']

    gdf = gpd.read_file(shapefile_path)

    # Coordinate Reference System: MUST BE 6933 for valid results unless testing
    EPSG = config['EPSG']

    # Ensure the CRS is consistent
    gdf = gdf.to_crs(epsg=EPSG)

    # Crop aggregation dictionary: maps crop categories to their rain and irrigated components
    crop_aggregation = config['crop_aggregation']

    # Country name mapping for consistency
    country_mapping = config['country_mapping']

    # Process each scenario of nuclear winter (different soot levels)
    for scenario in scenarios[5:]:
        logging.info(f"Processing scenario: {scenario['name']}")
        process_scenario(
            scenario_name=scenario['name'],
            crop_file_paths=scenario['crop_files'],
            grass_file_paths=scenario['grass_files'],
            control_crop_files=control_crop_files,
            control_grass_files=control_grass_files,
            gdf=gdf,
            crop_aggregation=crop_aggregation,
            country_mapping=country_mapping,
            EPSG=EPSG,
            years=config['years']
        )


if __name__ == '__main__':
    main()
