document.addEventListener('click', (event) => {
  const opener = event.target.closest('[data-dialog-open]');
  if (opener) {
    const dialog = document.getElementById(opener.dataset.dialogOpen);
    if (dialog instanceof HTMLDialogElement) dialog.showModal();
    return;
  }

  const closer = event.target.closest('[data-dialog-close]');
  if (closer) {
    const dialog = closer.closest('dialog');
    if (dialog instanceof HTMLDialogElement) dialog.close();
  }
});

document.addEventListener('submit', (event) => {
  const submitter = event.submitter;
  if (!(submitter instanceof HTMLElement)) return;
  const message = submitter.dataset.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});
