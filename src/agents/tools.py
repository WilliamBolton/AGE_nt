from Bio import Entrez

def search_pubmed(query: str) -> str:
    """Real PubMed search using Biopython."""
    Entrez.email = "your_email@example.com"  # Replace with your actual email
    
    # 1. Search for PMIDs (PubMed IDs)
    handle = Entrez.esearch(db="pubmed", term=query, retmax=3)
    record = Entrez.read(handle)
    handle.close()
    
    id_list = record["IdList"]
    if not id_list:
        return f"No results found for {query}."

    # 2. Fetch the actual abstracts/details
    handle = Entrez.efetch(db="pubmed", id=",".join(id_list), rettype="medline", retmode="text")
    data = handle.read()
    handle.close()
    
    return data

# def search_pubmed(query: str) -> str:
#     """Searches PubMed for a gene and returns a snippet of text."""
#     # In a real scenario, use Entrez. For now, a simulated response:
#     return f"Latest research on {query} suggests a link to inflammatory pathways."

