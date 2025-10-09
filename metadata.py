from typing import Dict, List, Optional, Union, cast

from pydantic import BaseModel, Field
from qdrant_client.http import models as rest

from main import logger


class FileInfo(BaseModel):
    """Model for file information with ID and name"""

    id: str = Field(..., description="ID of the file")
    name: str = Field(..., description="Name of the file")


class FolderInfo(BaseModel):
    """Model for folder information with ID and name"""

    id: str = Field(..., description="ID of the folder")
    name: str = Field(..., description="Name of the folder")


class KBCluster(BaseModel):
    """Model for Knowledge Base cluster with selected files"""

    cluster_id: str = Field(..., description="ID of the knowledge base cluster")
    name: str = Field(default="", description="Name of the knowledge base cluster")
    folder_ids: Optional[List[Union[str, FolderInfo]]] = Field(
        default=[],
        description="List of folder IDs or folder info objects within the site",
    )
    file_ids: List[Union[str, FileInfo]] = Field(
        default=[],
        description="List of file IDs or file info objects within the cluster",
    )


class SPCluster(BaseModel):
    """Model for SharePoint cluster with selected folders and files"""

    site_doc_id: str = Field(..., description="ID of the SharePoint site document")
    name: str = Field(default="", description="Name of the SharePoint site document")
    folder_ids: List[Union[str, FolderInfo]] = Field(
        default=[],
        description="List of folder IDs or folder info objects within the site",
    )
    file_ids: List[Union[str, FileInfo]] = Field(
        default=[], description="List of file IDs or file info objects within the site"
    )


class ProposalCluster(BaseModel):
    """Model for Proposal cluster with selected files"""

    cluster_id: str = Field(..., description="ID of the proposal cluster")
    name: str = Field(default="", description="Name of the proposal cluster")
    file_ids: List[Union[str, FileInfo]] = Field(
        default=[],
        description="List of file IDs or file info objects within the cluster",
    )


class DataSources(BaseModel):
    """Model for data sources selection"""

    kb_clusters: List[KBCluster] = Field(
        default=[], description="Selected knowledge base clusters with files"
    )
    sp_clusters: List[SPCluster] = Field(
        default=[], description="Selected SharePoint clusters with folders and files"
    )
    proposal_clusters: Optional[List[ProposalCluster]] = Field(
        default=[], description="Selected proposal clusters with files"
    )

    def _get_file_id(self, file_item: Union[str, FileInfo]) -> str:
        """Extract file ID from either string or FileInfo object"""
        if isinstance(file_item, str):
            return file_item
        return file_item.id

    def _get_folder_id(self, folder_item: Union[str, FolderInfo]) -> str:
        """Extract folder ID from either string or FolderInfo object"""
        if isinstance(folder_item, str):
            return folder_item
        return folder_item.id

    def get_kb_file_ids(self, cluster_id: str) -> List[str]:
        """Get all file IDs for a specific KB cluster"""
        for cluster in self.kb_clusters:
            if cluster.cluster_id == cluster_id:
                return [self._get_file_id(file_item) for file_item in cluster.file_ids]
        return []

    def get_sp_file_ids(self, site_doc_id: str) -> List[str]:
        """Get all file IDs for a specific SP cluster"""
        for cluster in self.sp_clusters:
            if cluster.site_doc_id == site_doc_id:
                return [self._get_file_id(file_item) for file_item in cluster.file_ids]
        return []

    def get_sp_folder_ids(self, site_doc_id: str) -> List[str]:
        """Get all folder IDs for a specific SP cluster"""
        for cluster in self.sp_clusters:
            if cluster.site_doc_id == site_doc_id:
                return [
                    self._get_folder_id(folder_item)
                    for folder_item in cluster.folder_ids
                ]
        return []


def filter_out_if_existing_multiple_metadata_tags(
    multiple_filter_tags: List[str],
) -> rest.Filter:
    """
    Setup the filter to query only Documents WITHOUT these multiple metadata.filter_tag

    When applying this filter, the retrieved documents MUST NOT have any of the {filter_tag}
    in {multiple_filter_tags} within their metadata tags.

    Inputs:
        multiple_filter_tags List[str]: List with the names of the metadata tags used to filter

    Returns:
        filter (rest.Filter): Filter object to be used when querying the Qdrant VectorDB
    """
    multiple_filter_conditions = []
    for filter_tag in multiple_filter_tags:
        multiple_filter_conditions.append(
            rest.IsEmptyCondition(
                is_empty=rest.PayloadField(key=f"metadata.{filter_tag}")
            )
        )
    filter = rest.Filter(must=multiple_filter_conditions)
    return filter


def filter_by_multiple_tag_must_value_conditions(
    multiple_filter_tags: List[Dict],
) -> rest.Filter:
    """
    Setup the filter to query only Documents that comply with {tag: value}

    When applying this filter, the retrieved documents MUST have the {tag}
    in {multiple_filter_tags} within their metadata.metadata_type tags. Additionally, the value of the tag MUST
    correspond to the indicated one.

    Inputs:
        multiple_filter_tags List[Dict]: List with the dicts of {tag:value}

    Returns:
        filter (rest.Filter): Filter object to be used when querying the Qdrant VectorDB
    """
    multiple_filter_conditions = []
    for condition_dict in multiple_filter_tags:
        for tag, value in condition_dict.items():
            multiple_filter_conditions.append(
                rest.FieldCondition(
                    key=f"metadata.{tag}",
                    match=rest.MatchValue(value=value),
                )
            )
    filter = rest.Filter(must=multiple_filter_conditions)
    return filter


def filter_by_multiple_tag_should_value_conditions(
    multiple_filter_tags: List[Dict],
) -> rest.Filter:
    """
    Setup the filter to query only Documents that comply with {tag: value}

    When applying this filter, the retrieved documents SHOULD have the at least one of the {tag}
    in {multiple_filter_tags} within their metadata.metadata_type tags. Additionally, the value of the tag MUST
    correspond to the indicated one.

    Inputs:
        multiple_filter_tags List[Dict]: List with the dicts of {tag:value} where any of those should be present

    Returns:
        filter (rest.Filter): Filter object to be used when querying the Qdrant VectorDB
    """
    multiple_filter_conditions = []
    for condition_dict in multiple_filter_tags:
        for tag, value in condition_dict.items():
            multiple_filter_conditions.append(
                rest.FieldCondition(
                    key=f"metadata.{tag}",
                    match=rest.MatchValue(value=value),
                )
            )
    filter = rest.Filter(should=multiple_filter_conditions)
    return filter


def filter_by_must_and_should_multiple_tag_value_conditions(
    must_have_filter_tags: List[Dict], should_have_filter_tags: List[Dict]
) -> rest.Filter:
    """
    Setup the filter to query only Documents that comply with {tag: value}

    When applying this filter, the retrieved documents MUST have the {tag}
    in {must_have_filter_tags} within their metadata.metadata_type tags, and SHOULD have at least one of the {tag} in {should_have_filter_tags}.
    Additionally, the value of the tag MUST correspond to the indicated one.

    Inputs:
        must_have_filter_tags List[Dict]: List with the dicts of {tag:value} that MUST be present.
        should_have_filter_tags List[Dict]: List with the dicts of {tag:value} where any of those should be present.

    Returns:
        filter (rest.Filter): Filter object to be used when querying the Qdrant VectorDB
    """
    must_have_filter_conditions = []
    should_have_filter_conditions = []
    for condition_dict in must_have_filter_tags:
        for tag, value in condition_dict.items():
            must_have_filter_conditions.append(
                rest.FieldCondition(
                    key=f"metadata.{tag}",
                    match=rest.MatchValue(value=value),
                )
            )
    for condition_dict in should_have_filter_tags:
        for tag, value in condition_dict.items():
            should_have_filter_conditions.append(
                rest.FieldCondition(
                    key=f"metadata.{tag}",
                    match=rest.MatchValue(value=value),
                )
            )

    filter = rest.Filter(
        must=must_have_filter_conditions, should=should_have_filter_conditions
    )
    return filter


def create_filter_for_datasources(
    data_sources: DataSources,
    cluster_ids: Optional[List[str]] = None,
    debug: bool = False,
) -> Optional[rest.Filter]:
    """
    Create a Qdrant filter based on the DataSources selection and optional legacy cluster_ids.

    Cases:
      1) For KB clusters:
         - If file_ids are empty: must match type=kb AND cluster_id
         - If file_ids are present: must match type=kb AND cluster_id AND file_id in <file_ids>
      2) For SharePoint clusters:
         - Must always match type=sharepoint
         - Should match either parent_ids in <folder_ids> OR file_id in <file_ids>
      3) Legacy cluster_ids (if provided): OR match metadata.cluster_id in <cluster_ids>
      4) Final filter is the union (OR) of all valid cluster-based filters.
      5) If no clusters and no legacy cluster_ids, return a filter that matches nothing.

    Args:
        data_sources (DataSources): The data sources configuration
        cluster_ids (Optional[List[str]]): Legacy cluster IDs for backward compatibility
        debug (bool): Whether to enable debug loggerging

    Returns:
        Optional[rest.Filter]: A Qdrant filter object, or None if no filtering is needed
    """
    # Debug input parameters
    if debug:
        try:
            logger.info(
                f"create_filter_for_datasources input: data_sources={data_sources}, cluster_ids={cluster_ids}"
            )
            if data_sources:
                logger.info(f"KB clusters: {data_sources.kb_clusters}")
                for kb in data_sources.kb_clusters:
                    logger.info(
                        f"  KB cluster: {kb.cluster_id}, files: {kb.file_ids}"
                    )
                logger.info(f"SP clusters: {data_sources.sp_clusters}")
        except Exception as e:
            logger.error(f"Error logging input parameters: {str(e)}")

    def get_file_id(file_item: Union[str, FileInfo]) -> str:
        """Extract file ID from either string or FileInfo object"""
        if isinstance(file_item, str):
            return file_item
        return file_item.id

    def get_folder_id(folder_item: Union[str, FolderInfo]) -> str:
        """Extract folder ID from either string or FolderInfo object"""
        if isinstance(folder_item, str):
            return folder_item
        return folder_item.id

    # Collect all subfilters we will OR together at the top level
    top_level_filters: List[rest.Filter] = []

    # -------------------------------------------------------------------------
    # Handle optional legacy cluster_ids as an OR condition
    # -------------------------------------------------------------------------
    if cluster_ids:
        try:
            # Create a filter that matches any of the legacy cluster_ids
            legacy_cluster_filter = rest.Filter(
                must=[
                    rest.FieldCondition(
                        key="metadata.cluster_id",
                        match=rest.MatchAny(any=cluster_ids),
                    )
                ]
            )
            top_level_filters.append(legacy_cluster_filter)
            if debug:
                logger.info(f"Added legacy cluster filter for: {cluster_ids}")
        except Exception as e:
            logger.error(f"Error creating legacy cluster filter: {str(e)}")

    # -------------------------------------------------------------------------
    # Process KB clusters
    # -------------------------------------------------------------------------
    for kb_cluster in data_sources.kb_clusters:
        try:
            if debug:
                print(f"Processing KB cluster: {kb_cluster}")

            # Create base conditions that must be satisfied
            must_conditions: List[rest.Condition] = [
                # rest.FieldCondition(
                #     key="metadata.type",
                #     match=rest.MatchValue(value="kb"),
                # ),
                rest.FieldCondition(
                    key="metadata.cluster_id",
                    match=rest.MatchValue(value=kb_cluster.cluster_id),
                ),
            ]

            # -----------------------------------------------------------------
            # New branching loggeric based on presence of folder_ids / file_ids
            #   • BOTH present  ➜ create TWO independent filters (OR at top-level)
            #   • Only one present ➜ single filter with that condition in MUST
            #   • None present    ➜ cluster wide filter (only cluster_id in MUST)
            # -----------------------------------------------------------------

            has_folders = bool(kb_cluster.folder_ids)
            has_files = bool(kb_cluster.file_ids)

            if has_folders and has_files:
                # --- Folder sub-filter ---
                folder_ids = [
                    get_folder_id(fid) for fid in (kb_cluster.folder_ids or [])
                ]
                folder_filter = rest.Filter(
                    must=[
                        *must_conditions,
                        rest.FieldCondition(
                            key="metadata.parent_ids",
                            match=rest.MatchAny(any=folder_ids),
                        ),
                    ]
                )
                top_level_filters.append(folder_filter)
                if debug:
                    logger.info(f"  Created KB folder filter: {folder_filter}")

                # --- File sub-filter ---
                file_ids = [get_file_id(fid) for fid in kb_cluster.file_ids]
                file_filter = rest.Filter(
                    must=[
                        *must_conditions,
                        rest.FieldCondition(
                            key="metadata.file_id",
                            match=rest.MatchAny(any=file_ids),
                        ),
                    ]
                )
                top_level_filters.append(file_filter)
                if debug:
                    logger.info(f"  Created KB file filter: {file_filter}")

            elif has_folders:
                folder_ids = [
                    get_folder_id(fid) for fid in (kb_cluster.folder_ids or [])
                ]
                kb_filter = rest.Filter(
                    must=[
                        *must_conditions,
                        rest.FieldCondition(
                            key="metadata.parent_ids",
                            match=rest.MatchAny(any=folder_ids),
                        ),
                    ]
                )
                top_level_filters.append(kb_filter)
                if debug:
                    logger.info(f"  Created KB filter (folders only): {kb_filter}")

            elif has_files:
                file_ids = [get_file_id(fid) for fid in kb_cluster.file_ids]
                kb_filter = rest.Filter(
                    must=[
                        *must_conditions,
                        rest.FieldCondition(
                            key="metadata.file_id",
                            match=rest.MatchAny(any=file_ids),
                        ),
                    ]
                )
                top_level_filters.append(kb_filter)
                if debug:
                    logger.info(f"  Created KB filter (files only): {kb_filter}")

            else:
                # No folders/files specified ➜ entire cluster
                kb_filter = rest.Filter(must=must_conditions)
                top_level_filters.append(kb_filter)
                if debug:
                    logger.info(
                        f"  Created KB broad filter (cluster only): {kb_filter}"
                    )

        except Exception as e:
            logger.error(f"Error processing KB cluster {kb_cluster}: {str(e)}")
            continue

    # -------------------------------------------------------------------------
    # Process Proposal clusters
    # -------------------------------------------------------------------------
    if data_sources.proposal_clusters is not None:
        for proposal_cluster in data_sources.proposal_clusters:
            try:
                if debug:
                    logger.info(f"Processing Proposal cluster: {proposal_cluster}")

                # Create base conditions that must be satisfied
                must_conditions: List[rest.Condition] = [
                    rest.FieldCondition(
                        key="metadata.type",
                        match=rest.MatchValue(value="pc"),
                    ),
                    rest.FieldCondition(
                        key="metadata.cluster_id",
                        match=rest.MatchValue(value=proposal_cluster.cluster_id),
                    ),
                ]

                # If file_ids are present, add file_id condition
                if proposal_cluster.file_ids:
                    file_ids = [get_file_id(fid) for fid in proposal_cluster.file_ids]
                    must_conditions.append(
                        rest.FieldCondition(
                            key="metadata.file_id",
                            match=rest.MatchAny(any=file_ids),
                        )
                    )
                    if debug:
                        logger.info(f"  Added file_ids condition: {file_ids}")

                # Create the Proposal filter with all conditions
                proposal_filter = rest.Filter(must=must_conditions)
                top_level_filters.append(proposal_filter)
                if debug:
                    logger.info(f"  Created Proposal filter: {proposal_filter}")

            except Exception as e:
                logger.error(
                    f"Error processing Proposal cluster {proposal_cluster}: {str(e)}"
                )
                continue

    # -------------------------------------------------------------------------
    # Process SharePoint clusters
    # -------------------------------------------------------------------------
    for sp_cluster in data_sources.sp_clusters:
        try:
            if debug:
                logger.info(f"Processing SP cluster: {sp_cluster}")

            # Base conditions that must be satisfied
            must_conditions: List[rest.Condition] = [
                rest.FieldCondition(
                    key="metadata.type",
                    match=rest.MatchValue(value="sharepoint"),
                )
            ]

            # Collect should conditions for folders and files
            should_conditions: List[rest.Condition] = []

            # Add folder condition if folder_ids exist
            if sp_cluster.folder_ids:
                folder_ids = [get_folder_id(fid) for fid in sp_cluster.folder_ids]
                should_conditions.append(
                    rest.FieldCondition(
                        key="metadata.parent_ids",
                        match=rest.MatchAny(any=folder_ids),
                    )
                )
                if debug:
                    logger.info(f"  Added folder_ids condition: {folder_ids}")

            # Add file condition if file_ids exist
            if sp_cluster.file_ids:
                file_ids = [get_file_id(fid) for fid in sp_cluster.file_ids]
                should_conditions.append(
                    rest.FieldCondition(
                        key="metadata.file_id",
                        match=rest.MatchAny(any=file_ids),
                    )
                )
                if debug:
                    logger.info(f"  Added file_ids condition: {file_ids}")

            # Create the SP filter
            if should_conditions:
                sp_filter = rest.Filter(
                    must=must_conditions,
                    should=should_conditions,
                )
                top_level_filters.append(sp_filter)
                if debug:
                    logger.info(f"  Created SP filter: {sp_filter}")
            else:
                # If no folders or files, create a filter that matches nothing
                # This ensures consistent behavior with the OR loggeric
                sp_filter = rest.Filter(
                    must=[
                        *must_conditions,
                        rest.FieldCondition(
                            key="metadata.non_existent_field",
                            match=rest.MatchValue(value="non_existent_value"),
                        ),
                    ]
                )
                top_level_filters.append(sp_filter)
                if debug:
                    logger.info("  Created empty SP filter (matches nothing)")

        except Exception as e:
            logger.error(f"Error processing SP cluster {sp_cluster}: {str(e)}")
            continue

    # -------------------------------------------------------------------------
    # Create final filter
    # -------------------------------------------------------------------------
    if not top_level_filters:
        if debug:
            logger.info("No valid filters created, returning None")
        return None

    if len(top_level_filters) == 1:
        final_filter = top_level_filters[0]
    else:
        # Convert top_level_filters to conditions for the final filter
        final_filter = rest.Filter(
            should=[cast(rest.Condition, f) for f in top_level_filters]
        )

    if debug:
        logger.info(f"Final filter created: {final_filter}")

    return final_filter


def create_filter_from_dict(
    data_sources_dict: Dict,
    cluster_ids: Optional[List[str]] = None,
    debug: bool = False,
) -> Optional[rest.Filter]:
    """
    Create a Qdrant filter from a dictionary representation of data sources.

    Args:
        data_sources_dict: Dictionary representation of data sources
        cluster_ids: Optional legacy cluster IDs
        debug: Whether to enable debug loggerging

    Returns:
        Optional[rest.Filter]: A Qdrant filter object
    """
    try:
        # Simply convert dict to DataSources object
        logger.info("Creating DataSources object from dict: %s", data_sources_dict)
        data_sources = DataSources.model_validate(data_sources_dict)

        # Call the existing function with the converted object
        return create_filter_for_datasources(data_sources, cluster_ids, debug)

    except Exception as e:
        logger.error(f"Error converting data_sources_dict to filter: {str(e)}")
        # Create fallback filter if we have cluster_id
        if (
            data_sources_dict
            and "kb_clusters" in data_sources_dict
            and data_sources_dict["kb_clusters"]
        ):
            cluster_id = data_sources_dict["kb_clusters"][0].get("cluster_id")
            if cluster_id:
                return rest.Filter(
                    must=[
                        rest.FieldCondition(
                            key="metadata.type", match=rest.MatchValue(value="kb")
                        ),
                        rest.FieldCondition(
                            key="metadata.cluster_id",
                            match=rest.MatchValue(value=cluster_id),
                        ),
                    ]
                )
        return None
