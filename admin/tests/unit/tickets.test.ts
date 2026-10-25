import { describe, expect, it } from 'vitest'
import { answerTicket, claimTicket, getTicket, listTickets, requestTicketInfo, saveTicketDraft } from '../../src/api/tickets'
import { uuidv7 } from '../../src/util/uuid'
import { loginAs } from '../helpers'

describe('专家工单（F2）', () => {
  it('普通 admin 无工单权限（403）', async () => {
    await loginAs('admin')
    await expect(listTickets({ page: 1, page_size: 50 })).rejects.toMatchObject({ code: 'FORBIDDEN', status: 403 })
  })

  it('expert 可查看队列并领取未分配工单', async () => {
    await loginAs('expert')
    const queue = await listTickets({ page: 1, page_size: 50, assignee: 'unassigned' })
    expect(queue.total).toBe(1)
    const ticketId = queue.items[0].ticket_id
    const claimed = await claimTicket(ticketId, { expected_version: 0 }, uuidv7())
    expect(claimed.status).toBe('reviewing')
    expect(claimed.assignee_display_name).toBe('专家')
  })

  it('重复领取已被领取的工单返回 409', async () => {
    await loginAs('expert')
    // 第二个工单已被种子数据分配给 expert
    const queue = await listTickets({ page: 1, page_size: 50, assignee: 'me' })
    const mine = queue.items.find((t) => t.status === 'reviewing')
    expect(mine).toBeTruthy()
    await expect(claimTicket(mine!.ticket_id, { expected_version: mine!.version }, uuidv7())).rejects.toMatchObject({ code: 'STATE_CONFLICT', status: 409 })
  })

  it('needs_info 期间不能直接答复', async () => {
    await loginAs('expert')
    const queue = await listTickets({ page: 1, page_size: 50, assignee: 'unassigned' })
    const ticketId = queue.items[0].ticket_id
    const claimed = await claimTicket(ticketId, { expected_version: 0 }, uuidv7())
    await requestTicketInfo(ticketId, { expected_version: claimed.version, request_text: '请补充叶片照片' }, uuidv7())
    const detail = await getTicket(ticketId)
    expect(detail.status).toBe('needs_info')
    await expect(answerTicket(ticketId, { expected_version: detail.version, answer_text: '答复' }, uuidv7())).rejects.toMatchObject({ code: 'STATE_CONFLICT', status: 409 })
  })

  it('草稿保存不改变状态，答复后关闭只读', async () => {
    await loginAs('expert')
    const queue = await listTickets({ page: 1, page_size: 50, assignee: 'unassigned' })
    const ticketId = queue.items[0].ticket_id
    const claimed = await claimTicket(ticketId, { expected_version: 0 }, uuidv7())
    const drafted = await saveTicketDraft(ticketId, { expected_version: claimed.version, draft: '草稿内容' }, uuidv7())
    expect(drafted.status).toBe('reviewing')
    expect(drafted.draft).toBe('草稿内容')
    const answered = await answerTicket(ticketId, { expected_version: drafted.version, answer_text: '溃疡病，建议药剂处理。' }, uuidv7())
    expect(answered.status).toBe('done')
    expect(answered.outcome).toBe('answered')
  })

  it('旧版本动作返回 409，不覆盖新结果', async () => {
    await loginAs('expert')
    const queue = await listTickets({ page: 1, page_size: 50, assignee: 'unassigned' })
    const ticketId = queue.items[0].ticket_id
    await claimTicket(ticketId, { expected_version: 0 }, uuidv7())
    await expect(answerTicket(ticketId, { expected_version: 0, answer_text: '旧版本答复' }, uuidv7())).rejects.toMatchObject({ code: 'VERSION_CONFLICT', status: 409 })
  })
})
