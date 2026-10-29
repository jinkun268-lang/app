import { request } from './http'
import type { Batch, BatchPage, CollectionQuestion, CollectionQuestionPage } from '../types'

export function listBatches(page = 1, pageSize = 20): Promise<BatchPage> {
  return request({ path: '/batches', query: { page, page_size: pageSize } })
}

export function listQuestions(page = 1, pageSize = 20): Promise<CollectionQuestionPage> {
  return request({ path: '/questions', query: { page, page_size: pageSize } })
}

export function getQuestion(id: string): Promise<CollectionQuestion> {
  return request({ path: `/questions/${encodeURIComponent(id)}` })
}

export function answerQuestion(id: string, answer: string): Promise<CollectionQuestion> {
  return request({ path: `/questions/${encodeURIComponent(id)}/answer`, method: 'PATCH', body: { answer } })
}
