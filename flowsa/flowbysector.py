# flowbysector.py (flowsa)
# !/usr/bin/env python3
# coding=utf-8
"""
Produces a FlowBySector data frame based on a method file for the given class
"""
import flowsa
import pandas as pd
import yaml
import argparse
from flowsa.common import log, flowbyactivitymethodpath, flow_by_sector_fields, \
    generalize_activity_field_names, outputpath, datapath, fips_number_key
from flowsa.mapping import add_sectors_to_flowbyactivity, get_fba_allocation_subset
from flowsa.flowbyfunctions import fba_activity_fields, fbs_default_grouping_fields, agg_by_geoscale, \
    fba_fill_na_dict, fbs_fill_na_dict, convert_unit, fba_default_grouping_fields, \
    add_missing_flow_by_fields, fbs_activity_fields, allocate_by_sector, allocation_helper, sector_aggregation
from flowsa.USGS_NWIS_WU import standardize_usgs_nwis_names


def load_method(method_name):
    """
    Loads a flowbysector method from a YAML
    :param method_name:
    :return:
    """
    sfile = flowbyactivitymethodpath + method_name + '.yaml'
    try:
        with open(sfile, 'r') as f:
            method = yaml.safe_load(f)
    except IOError:
        log.error("File not found.")
    return method


def store_flowbysector(fbs_df, parquet_name):
    """Prints the data frame into a parquet file."""
    f = outputpath + parquet_name + '.parquet'
    try:
        fbs_df.to_parquet(f)
    except:
        log.error('Failed to save ' + parquet_name + ' file.')


def main(method_name):
    """
    Creates a flowbysector dataset
    :param method_name: Name of method corresponding to flowbysector method yaml name
    :return: flowbysector
    """

    log.info("Initiating flowbysector creation for " + method_name)
    # call on method
    method = load_method(method_name)
    # create dictionary of water data and allocation datasets
    fbas = method['flowbyactivity_sources']
    # Create empty list for storing fbs files
    fbss = []
    for k, v in fbas.items():
        # pull water data for allocation
        log.info("Retrieving flowbyactivity for datasource " + k + " in year " + str(v['year']))
        flows = flowsa.getFlowByActivity(flowclass=[v['class']],
                                         years=[v['year']],
                                         datasource=k)
        # if allocating USGS NWIS water data, first standardize names in data set
        if k == 'USGS_NWIS_WU':
            flows = standardize_usgs_nwis_names(flows)

        # drop description field
        flows = flows.drop(columns='Description')
        # fill null values
        flows = flows.fillna(value=fba_fill_na_dict)
        # convert unit
        log.info("Converting units in " + k)
        flows = convert_unit(flows)


        # create dictionary of allocation datasets for different usgs activities
        activities = v['activity_sets']
        for aset, attr in activities.items():
            # subset by named activities
            names = [attr['names']]
            log.info("Preparing to handle subset of flownames " + ', '.join(map(str, names)) + " in " + k)
            # subset usgs data by activity
            flow_subset = flows[(flows[fba_activity_fields[0]].isin(names)) |
                                (flows[fba_activity_fields[1]].isin(names))]

            # Reset index values after subset
            flow_subset = flow_subset.reset_index()

            # aggregate geographically to the scale of the allocation dataset
            from_scale = v['geoscale_to_use']
            to_scale = attr['allocation_from_scale']
            # if usgs is less aggregated than allocation df, aggregate usgs activity to target scale
            log.info("Aggregating subset from " + from_scale + " to " + to_scale)
            if fips_number_key[from_scale] > fips_number_key[to_scale]:
                flow_subset = agg_by_geoscale(flow_subset, from_scale, to_scale, fba_default_grouping_fields, names)
            # else, if usgs is more aggregated than allocation table, use usgs as both to and from scale
            else:
                flow_subset = agg_by_geoscale(flow_subset, from_scale, from_scale, fba_default_grouping_fields, names)

            # location column pad zeros if necessary
            flow_subset['Location'] = flow_subset['Location'].apply(lambda x: x.ljust(3 + len(x), '0') if len(x) < 5
            else x)

            # Add sectors to usgs activity, creating two versions of the flow subset
            # the first version "flow_subset" is the most disaggregated version of the Sectors (NAICS)
            # the second version, "flow_subset_agg" includes only the most aggregated level of sectors
            log.info("Adding sectors to " + k)
            flow_subset_wsec = add_sectors_to_flowbyactivity(flow_subset,
                                                             sectorsourcename=method['target_sector_source'])
            flow_subset_wsec_agg = add_sectors_to_flowbyactivity(flow_subset,
                                                                 sectorsourcename=method['target_sector_source'],
                                                                 levelofSectoragg='agg')

            # if allocation method is "direct", then no need to create alloc ratios, else need to use allocation
            # dataframe to create sector allocation ratios
            if attr['allocation_method'] == 'direct':
                fbs = flow_subset_wsec_agg.copy()
            else:
                # determine appropriate allocation dataset
                log.info("Loading allocation flowbyactivity " + attr['allocation_source'] + " for year " + str(attr['allocation_source_year']))
                fba_allocation = flowsa.getFlowByActivity(flowclass=[attr['allocation_source_class']],
                                                          datasource=attr['allocation_source'],
                                                          years=[attr['allocation_source_year']])

                # aggregate geographically to the scale of the flowbyactivity source, if necessary
                from_scale = attr['allocation_from_scale']
                to_scale = v['geoscale_to_use']
                # if usgs is less aggregated than allocation df, aggregate usgs activity to target scale
                log.info("Aggregating " + attr['allocation_source'] + " from " + from_scale + " to " + to_scale)
                if fips_number_key[from_scale] > fips_number_key[to_scale]:
                    fba_allocation = agg_by_geoscale(fba_allocation, from_scale, to_scale, fba_default_grouping_fields, names)
                # else, if usgs is more aggregated than allocation table, use usgs as both to and from scale
                else:
                    fba_allocation = agg_by_geoscale(fba_allocation, from_scale, from_scale, fba_default_grouping_fields, names)

                # fill null values
                fba_allocation = fba_allocation.fillna(value=fba_fill_na_dict)
                # convert unit
                fba_allocation = convert_unit(fba_allocation)
                # subset based on yaml settings
                if attr['allocation_flow'] != 'None':
                    fba_allocation = fba_allocation.loc[fba_allocation['FlowName'].isin(attr['allocation_flow'])]
                if attr['allocation_compartment'] != 'None':
                    fba_allocation = fba_allocation.loc[
                        fba_allocation['Compartment'].isin(attr['allocation_compartment'])]

                # assign naics to allocation dataset
                log.info("Adding sectors to " + attr['allocation_source'])
                fba_allocation = add_sectors_to_flowbyactivity(fba_allocation,
                                                               sectorsourcename=method['target_sector_source'],
                                                               levelofSectoragg=attr[
                                                                   'allocation_sector_aggregation'])
                # subset fba datsets to only keep the naics associated with usgs activity subset
                log.info("Subsetting " + attr['allocation_source'] + " for sectors in " + k)
                fba_allocation_subset = get_fba_allocation_subset(fba_allocation, k, names)
                # Reset index values after subset
                fba_allocation_subset = fba_allocation_subset.reset_index(drop=True)
                # generalize activity field names to enable link to water withdrawal table
                log.info("Generalizing activity names in subset of " + attr['allocation_source'])
                fba_allocation_subset = generalize_activity_field_names(fba_allocation_subset)
                # drop columns
                fba_allocation_subset = fba_allocation_subset.drop(columns=['Activity'])
                # fba_allocation_subset = fba_allocation_subset.drop(
                #     columns=['Activity', 'Description', 'Min', 'Max'])
                # if there is an allocation helper dataset, modify allocation df
                if attr['allocation_helper'] == 'yes':
                    log.info("Using the specified allocation help for subset of " + attr['allocation_source'])
                    fba_allocation_subset = allocation_helper(fba_allocation_subset, method, attr)
                # create flow allocation ratios
                log.info("Creating allocation ratios for " + attr['allocation_source'])
                flow_allocation = allocate_by_sector(fba_allocation_subset, attr['allocation_method'])

                # create list of sectors in the flow allocation df, drop any rows of data in the flow df that \
                # aren't in list
                sector_list = flow_allocation['Sector'].unique().tolist()

                # subset fba allocation table to the values in the activity list, based on overlapping sectors
                flow_subset_wsec = flow_subset_wsec.loc[
                    (flow_subset_wsec[fbs_activity_fields[0]].isin(sector_list)) |
                    (flow_subset_wsec[fbs_activity_fields[1]].isin(sector_list))]

                # merge water withdrawal df w/flow allocation dataset
                # todo: modify to recalculate data quality scores

                log.info("Merge " + k + " and subset of " + attr['allocation_source'])
                fbs = flow_subset_wsec.merge(
                    flow_allocation[['Location', 'LocationSystem', 'Sector', 'FlowAmountRatio']],
                    left_on=['Location', 'LocationSystem', 'SectorProducedBy'],
                    right_on=['Location', 'LocationSystem', 'Sector'], how='left')

                fbs = fbs.merge(
                    flow_allocation[['Location', 'LocationSystem', 'Sector', 'FlowAmountRatio']],
                    left_on=['Location', 'LocationSystem', 'SectorConsumedBy'],
                    right_on=['Location', 'LocationSystem', 'Sector'], how='left')

                # drop columns where both sector produced/consumed by in flow allocation dif is null
                fbs = fbs.dropna(subset=['Sector_x', 'Sector_y'], how='all').reset_index()

                # merge the flowamount columns
                fbs['FlowAmountRatio'] = fbs['FlowAmountRatio_x'].fillna(fbs['FlowAmountRatio_y'])
                fbs['FlowAmountRatio'] = fbs['FlowAmountRatio'].fillna(0)

                # calculate flow amounts for each sector
                log.info("Calculating new flow amounts using flow ratios")
                fbs['FlowAmount'] = fbs['FlowAmount'] * fbs['FlowAmountRatio']

                # drop columns
                log.info("Cleaning up new flow by sector")
                fbs = fbs.drop(columns=['Sector_x', 'FlowAmountRatio_x', 'Sector_y', 'FlowAmountRatio_y',
                                        'FlowAmountRatio', 'ActivityProducedBy', 'ActivityConsumedBy'])

            # rename flow name to flowable
            fbs = fbs.rename(columns={"FlowName": 'Flowable',
                                      "Compartment": "Context"
                                      })

            # drop rows where flowamount = 0 (although this includes dropping suppressed data)
            fbs = fbs[fbs['FlowAmount'] != 0].reset_index(drop=True)
            # add missing data columns
            fbs = add_missing_flow_by_fields(fbs, flow_by_sector_fields)
            # fill null values
            fbs = fbs.fillna(value=fbs_fill_na_dict)

            # aggregate df geographically, if necessary
            log.info("Aggregating flowbysector to target geographic scale")
            if fips_number_key[v['geoscale_to_use']] <= fips_number_key[method['target_geoscale']]:
                from_scale = method['target_geoscale']
                to_scale = method['target_geoscale']
            else:
                from_scale = attr['allocation_from_scale']
                to_scale = method['target_geoscale']
            # aggregate usgs activity to target scale
            fbs = agg_by_geoscale(fbs, from_scale, to_scale, fbs_default_grouping_fields, names)

            # aggregate data to every sector level
            log.info("Aggregating flowbysector to target sector scale")
            fbs = sector_aggregation(fbs, fbs_default_grouping_fields)

            # return sector level specified in method yaml
            cw = pd.read_csv(datapath + "NAICS_2012_Crosswalk.csv", dtype="str")
            sector_list = cw[method['target_sector_level']].unique().tolist()
            fbs = fbs.loc[(fbs[fbs_activity_fields[0]].isin(sector_list)) |
                                     (fbs[fbs_activity_fields[1]].isin(sector_list))].reset_index(drop=True)

            # save as parquet file
            #parquet_name = method_name + '_' + attr['names']
            #store_flowbysector(fbs, parquet_name)
            log.info("Completed flowbysector for activity subset with flows " + ', '.join(map(str, names)))
            fbss.append(fbs)
    fbss = pd.concat(fbss, ignore_index=True, sort=False)
    store_flowbysector(fbss,method_name)

def parse_args():
    """Make year and source script parameters"""
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--method", required=True, help="Method for flow by sector file. A valid method config file must exist with this name.")
    args = vars(ap.parse_args())
    return args


if __name__ == '__main__':
    # assign arguments
    args = parse_args()
    main(args["method"])

