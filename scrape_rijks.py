# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "lxml",
#     "httpx",
#     "pandas",
#     "tqdm",
#     "datasets",
# ]
# ///
import httpx
import lxml.etree
from tqdm.auto import tqdm
import pandas as pd
from datasets import Dataset

params = {
    "verb": "ListRecords",
    "metadataPrefix": "edm",
}

namespaces = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "edm": "http://www.europeana.eu/schemas/edm/",
    "svcs": "http://rdfs.org/sioc/services/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdaGr2": "http://rdvocab.info/ElementsGr2/",
    "ore": "http://www.openarchives.org/ore/terms/",
    "edmfp": "http://www.europeanafashion.eu/edmfp/",
    "mrel": "http://id.loc.gov/vocabulary/relators/",
}

csv_header_written = False  # Flag to track if header has been written
with httpx.Client() as client:
    response = client.get("https://data.rijksmuseum.nl/oai", params=params)

    tree = lxml.etree.fromstring(response.content)

    total_records = int(
        tree.xpath(".//oai:resumptionToken/@completeListSize", namespaces=namespaces)[0]
    )

    with tqdm(total=total_records) as pbar:
        while True:
            tree = lxml.etree.fromstring(response.content)

            batch = tree.xpath(".//oai:record", namespaces=namespaces)
            records = []

            for i, record in enumerate(batch):
                object_id = record.xpath(
                    ".//oai:identifier/text()", namespaces=namespaces
                ) or [None]
                title = record.xpath(".//dc:title/text()", namespaces=namespaces) or [
                    None
                ]
                description = record.xpath(
                    ".//dc:description/text()", namespaces=namespaces
                ) or [None]
                image_url = (
                    record.xpath(
                        ".//edm:object/edm:WebResource/@rdf:about",
                        namespaces=namespaces,
                    )
                    or record.xpath(
                        ".//edm:object/@rdf:resource", namespaces=namespaces
                    )
                    or [None]
                )
                artist_uri = record.xpath(
                    ".//dc:creator/@rdf:resource", namespaces=namespaces
                ) or [None]

                artist_name = None
                if artist_uri and artist_uri[0]:
                    artist_description_element = record.xpath(
                        f".//rdf:Description[@rdf:about='{artist_uri[0]}']",
                        namespaces=namespaces,
                    )
                    if artist_description_element:
                        artist_name_list = artist_description_element[0].xpath(
                            "./skos:prefLabel/text()", namespaces=namespaces
                        )
                        artist_name = artist_name_list[0] if artist_name_list else None

                rights = record.xpath(
                    ".//edm:rights/@rdf:resource", namespaces=namespaces
                )
                # Skip non public domain records
                if "http://creativecommons.org/publicdomain/mark/1.0/" not in rights:
                    continue

                data = dict(
                    original_id=object_id[0],
                    image_url=image_url[0],
                    title=title[0],
                    description=description[0],
                    artist_uri=artist_uri[0],
                    artist_name=artist_name,
                )
                records.append(data)

            df_batch = pd.DataFrame(records)
            df_batch.to_csv(
                "data/rijks.csv", mode="a", header=not csv_header_written, index=False
            )
            csv_header_written = True

            pbar.update(len(records))

            resumption_token_list = tree.xpath(
                ".//oai:resumptionToken/text()", namespaces=namespaces
            )
            if resumption_token_list:
                params = {
                    "verb": "ListRecords",
                    "resumptionToken": resumption_token_list[0],
                }
                response = client.get("https://data.rijksmuseum.nl/oai", params=params)
            else:
                break

ds = Dataset.from_csv("data/rijks.csv")
print(ds)
ds.push_to_hub(repo_id="vincentmin/rijksmuseum-oai")
