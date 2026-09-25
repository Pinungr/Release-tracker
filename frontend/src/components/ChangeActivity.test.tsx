import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ChangeActivity } from './ChangeActivity'
import { api } from '../services/api'
vi.mock('../services/api', () => ({ api: {
  listCommentImages: vi.fn().mockResolvedValue({images: [], next_before_id: null}), getCommentImage: vi.fn().mockRejectedValue(new Error('No preview in test')),
  uploadComment: vi.fn().mockResolvedValue({}), downloadCommentAttachment: vi.fn().mockResolvedValue(undefined), getBookingComments: vi.fn().mockResolvedValue([]), addBookingComment: vi.fn().mockResolvedValue({}), getBookingAudit: vi.fn().mockResolvedValue([]),
}, ApiError: class extends Error {} }))
afterEach(cleanup)
it('lets a tenant post a public comment and read scoped history', async () => {
  render(<ChangeActivity bookingId={7} isAdmin={false} timezone="Asia/Kolkata" revision="1" />)
  await screen.findByText('No comments yet. Start the conversation.')
  expect(screen.queryByRole('checkbox')).toBeNull()
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Please review' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add comment' }))
  await waitFor(() => expect(api.addBookingComment).toHaveBeenCalledWith(7, 'Please review', false))
  fireEvent.click(screen.getByRole('tab', { name: 'Audit history' }))
  await waitFor(() => expect(api.getBookingAudit).toHaveBeenCalledWith(7))
})
it('clearly labels internal notes and renders text without executing HTML', async () => {
  vi.mocked(api.getBookingComments).mockResolvedValueOnce([{ id: 1, body: '<script>bad()</script>', internal: true, author_id: 2, author_name: 'RM', created_at: '2026-10-01T10:00:00Z' }])
  const { container } = render(<ChangeActivity bookingId={7} isAdmin timezone="Asia/Kolkata" revision="1" />)
  expect(await screen.findByText('<script>bad()</script>')).toBeTruthy()
  expect(container.querySelector('script')).toBeNull()
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Internal update' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add internal note' }))
  await waitFor(() => expect(api.addBookingComment).toHaveBeenCalledWith(7, 'Internal update', true))
})

it('blocks files above 20 MB and posts valid attachments with their comment', async () => {
 render(<ChangeActivity bookingId={7} isAdmin={false} timezone="Asia/Kolkata" revision="1" />)
 await screen.findByText('No comments yet. Start the conversation.')
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'Please see attached'}})
 const tooLarge = new File(['x'],'big.txt',{type:'text/plain'})
 Object.defineProperty(tooLarge,'size',{value:20*1024*1024+1})
 fireEvent.change(screen.getByLabelText('Attach files · 20 MB maximum per file'),{target:{files:[tooLarge]}})
 expect(screen.getByText('Each file must be 20 MB or smaller.')).toBeTruthy()
 expect((screen.getByRole('button',{name:'Add comment'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'Remove big.txt'}))
 const valid = new File(['evidence'],'report.txt',{type:'text/plain'})
 fireEvent.change(screen.getByLabelText('Attach files · 20 MB maximum per file'),{target:{files:[valid]}})
 fireEvent.click(screen.getByRole('button',{name:'Add comment'}))
 await waitFor(()=>expect(api.uploadComment).toHaveBeenCalledWith(7,'Please see attached',false,[valid]))
})


it('inserts an emoji at the cursor and submits Unicode text', async () => {
 render(<ChangeActivity bookingId={7} isAdmin={false} timezone="UTC" revision="1" />)
 await screen.findByText('No comments yet. Start the conversation.')
 const box = screen.getByRole('textbox') as HTMLTextAreaElement
 fireEvent.change(box,{target:{value:'Ready now'}})
 box.setSelectionRange(5,5)
 fireEvent.click(screen.getByRole('button',{name:'Add emoji'}))
 fireEvent.click(screen.getByRole('button',{name:'Launch'}))
 expect(box.value).toBe('Ready🚀 now')
 fireEvent.click(screen.getByRole('button',{name:'Add comment'}))
 await waitFor(()=>expect(api.addBookingComment).toHaveBeenCalledWith(7,'Ready🚀 now',false))
})

it('references an existing uploaded image without uploading its bytes again', async () => {
 vi.mocked(api.listCommentImages).mockResolvedValueOnce({images:[{kind:'comment',attachment_id:'abc',comment_id:12,original_filename:'proof.png',internal:false}],next_before_id:null})
 render(<ChangeActivity bookingId={7} isAdmin={false} timezone="UTC" revision="1" />)
 await screen.findByText('No comments yet. Start the conversation.')
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'See this image'}})
 fireEvent.click(screen.getByRole('button',{name:'Insert uploaded image'}))
 fireEvent.click(await screen.findByRole('button',{name:/proof.png/}))
 expect(await screen.findByRole('button',{name:'Remove image proof.png'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'Add comment'}))
 await waitFor(()=>expect(api.addBookingComment).toHaveBeenCalledWith(7,'See this image',false,[{kind:'comment',attachment_id:'abc',comment_id:12}]))
 await waitFor(()=>expect(screen.queryByRole('button',{name:'Remove image proof.png'})).toBeNull())
})

it('removes an internal image when an RM switches the draft to public', async () => {
 vi.mocked(api.listCommentImages).mockResolvedValueOnce({images:[{kind:'comment',attachment_id:'private',comment_id:13,original_filename:'internal.png',internal:true}],next_before_id:null})
 render(<ChangeActivity bookingId={7} isAdmin timezone="UTC" revision="1" />)
 await screen.findByText('No comments yet. Start the conversation.')
 fireEvent.click(screen.getByRole('checkbox'))
 fireEvent.click(screen.getByRole('button',{name:'Insert uploaded image'}))
 fireEvent.click(await screen.findByRole('button',{name:/internal.png/}))
 expect(await screen.findByRole('button',{name:'Remove image internal.png'})).toBeTruthy()
 fireEvent.click(screen.getByRole('checkbox'))
 expect(screen.queryByRole('button',{name:'Remove image internal.png'})).toBeNull()
 expect(screen.getByText('Internal RM images were removed when switching to a public comment.')).toBeTruthy()
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'Public update'}})
 fireEvent.click(screen.getByRole('button',{name:'Add comment'}))
 await waitFor(()=>expect(api.addBookingComment).toHaveBeenCalledWith(7,'Public update',false))
})
