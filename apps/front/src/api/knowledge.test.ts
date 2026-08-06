import { strict as assert } from 'node:assert'
import {
  normalizeKnowledgeBaseInput,
  type KnowledgeBaseInput,
} from './knowledge'

const input: KnowledgeBaseInput = {
  name: '测试',
  slug: 'test',
  embedding_model: 'text-embedding-3-small',
  embedding_base_url: '',
  embedding_api_key: '',
  embedding_dimension: 1536,
  chunk_size: 512,
  chunk_overlap: 50,
  retrieval_threshold: 0.5,
  retrieval_top_k: 5,
}

const normalized = normalizeKnowledgeBaseInput(input)

assert.equal(normalized.embedding_base_url, undefined)
assert.equal(normalized.embedding_api_key, undefined)

assert.deepEqual(
  normalizeKnowledgeBaseInput({
    embedding_base_url: ' https://api.example.com ',
    embedding_api_key: ' sk-test ',
  }),
  {
    embedding_base_url: 'https://api.example.com',
    embedding_api_key: 'sk-test',
  }
)
