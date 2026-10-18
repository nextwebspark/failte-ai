import { redirect } from 'next/navigation';

/**
 * Agents are created in the Create agent dialog on the Voice agents page. This
 * route stays for sign-in redirects, impersonation and old links, and opens
 * that dialog.
 */
export default function CreateWorkflowPage() {
    redirect('/workflow?create=describe');
}
