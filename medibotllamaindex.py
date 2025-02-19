import os
from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.core import Settings, StorageContext, VectorStoreIndex, SimpleDirectoryReader, QueryBundle
from pinecone import Pinecone
from llama_index.vector_stores.pinecone import PineconeVectorStore
from llama_index.core.schema import MetadataMode

#from llama_index.core import PromptTemplate
from llama_index.core.prompts import PromptTemplate


from llama_index.core.node_parser import SentenceWindowNodeParser
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.node_parser import JSONNodeParser
from llama_index.core import Settings
from llama_index.core import SimpleDirectoryReader
from llama_index.core import VectorStoreIndex
from llama_index.core.response.notebook_utils import display_source_node
from llama_index.postprocessor.rankgpt_rerank import RankGPTRerank


import json
import hashlib

from flask import Flask, request, Response

from waitress import serve
from flask_cors import CORS
#import logging
#import sys

#logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
#logging.getLogger().addHandler(logging.StreamHandler(stream=sys.stdout))

#pinecone_client = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
#pinecone_index = pinecone_client.Index("docchat")


# create the sentence window node parser w/ default settings
node_parser = SentenceWindowNodeParser.from_defaults(
    window_size=5,
    window_metadata_key="window",
    original_text_metadata_key="original_text",
)

# Build llm models
llm = Bedrock(
    model="mistral.mixtral-8x7b-instruct-v0:1",
    temperature=0,
    timeout=60,
    context_size=10000,
    max_tokens=2000,
)

#batch size=1000 takes 5 minutes 30 seconds to start
embed_model = BedrockEmbedding(
    #model = "amazon.titan-embed-text-v1",
    model = "cohere.embed-english-v3",
    )
Settings.llm =llm
Settings.embed_model = embed_model
Settings.node_parser = SentenceSplitter(chunk_size=200, chunk_overlap=10)
#JSONNodeParser()
#SentenceSplitter(chunk_size=200, chunk_overlap=10)

#JSONNodeParser()
#Settings.chunk_size = 512
#
documents = SimpleDirectoryReader("htmlpages/knowledge/", recursive=True).load_data()

# Transform chunks into numerical vectors using the embedding model
#index = VectorStoreIndex.from_documents(documents)
# Create a PineconeVectorStore using the specified pinecone_index
#vector_store = PineconeVectorStore(pinecone_index=pinecone_index)

# Create a StorageContext using the created PineconeVectorStore
#storage_context = StorageContext.from_defaults(
#    vector_store=vector_store
#)

# Use the chunks of documents and the storage_context to create the index
#index = VectorStoreIndex.from_documents(
#    documents, 
#    storage_context=storage_context
#)

index = VectorStoreIndex.from_documents(documents)
retriever = index.as_retriever(similarity_top_k=5, verbose=True)

reranker = RankGPTRerank(
    top_n = 5,
    llm = llm,
)

# Build a prompt template to only provide answers based on the loaded documents 
template = (
"We have provided context information below. \n"
    "---------------------\n"
    "{context_str}"
    "\n---------------------\n"
    "Given this information, please answer the question: {query_str}\n"
    "Don't give an answer unless it is supported by the context above.\n"
    "Provide all urls of the context where the answer is found.\n"
    "Use the file name of the context as the url.\n"
)

qa_template = PromptTemplate(template)

def getQueryResult(query):
    # display source for debug purpose
    nodes = retriever.retrieve(query)
    #pre_context_list = [n.get_content(metadata_mode=MetadataMode.ALL) for n in nodes]
    #print("\n\n".join(pre_context_list))
    query_bundle = QueryBundle(query_str=query)
    ranked_nodes = reranker._postprocess_nodes(nodes, query_bundle = query_bundle)
    # Retrieve the context from the model
    context_list = [n.get_content(metadata_mode=MetadataMode.ALL) for n in ranked_nodes]
    print("\n\n".join(context_list))
    prompt = qa_template.format(context_str="\n\n".join(context_list), query_str=query)

    # Generate the response 
    response = llm.complete(prompt)
    return str(response)

app = Flask(__name__)
CORS(app)

cache = {}

def do_query(usermessage) -> str:
    """
    query llm for the given usermessage, return result as a json str
    """
    key = 'get_chat'
    args_string = key+"{'usermessage': '" + usermessage + "}"
    # Use hashlib to create a hash of the query string for a unique and consistent cache key
    key_hash = hashlib.md5(args_string.encode('utf-8')).hexdigest()
    data = cache.get(key_hash)
    if (data is None):
        response = getQueryResult(usermessage)
        data=str(response)
        cache[key_hash] = data
    res = {}
    res["data"] = data
    res_json = json.dumps(res)
    return res_json

@app.post('/medibot/chat')
def on_get_chat():
    req = request.get_json()
    usermessage = req.get('usermessage', '')
    if not usermessage:
        return Response(json.dumps({"error": "Usermessage not provided"}), status=400, mimetype='application/json')

    res_json = do_query(usermessage)
    return Response(response=res_json, status=201, mimetype='application/json', headers={'Access-Control-Allow-Origin': '*'})

@app.get('/medibot/chat')
def on_chat():
    """
    make the chatbot accessible from broswer directly
    """
    usermessage = request.args.get('usermessage')
    if not usermessage:
        return Response(json.dumps({"error": "Usermessage not provided"}), status=400, mimetype='application/json')
    res_json = do_query(usermessage)
    return Response(response=res_json, status=201, mimetype='application/json', headers={'Access-Control-Allow-Origin': '*'})    

@app.get('/health/liveness')
def on_get_liveness():
    return Response(response='OK', status=200)

@app.get('/health/readiness')
def on_get_rediness():
    return Response(response='OK', status=200)

if __name__ == '__main__':
    serve(app, host="0.0.0.0", port=8080)
