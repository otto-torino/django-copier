;(function ($) {
  const form = document.getElementById('changelist-form')
  const savePositionUrl = form.dataset.savePositionUrl
  const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value

  // Add a block: the dialog of the types, from the toolbar at the end of the
  // page, from a "+" of the list right there
  const initAdd = () => {
    const dialog = document.getElementById('add-block-dialog')
    const note = dialog.querySelector('[data-insert-note]')
    const open = (button) => {
      const after = button.dataset.after || ''
      dialog.querySelectorAll('[data-add-url]').forEach((link) => {
        link.href = link.dataset.addUrl + (after ? '&after=' + encodeURIComponent(after) : '')
      })
      if (after === 'start') {
        note.textContent = dialog.dataset.startMessage
      } else if (after) {
        note.textContent = dialog.dataset.afterMessage.replace('%(name)s', button.dataset.afterName)
      }
      note.hidden = !after
      dialog.showModal()
    }
    document.querySelectorAll('[data-add-block]').forEach((button) => {
      button.addEventListener('click', () => open(button))
    })
    dialog.querySelector('[data-close-dialog]').addEventListener('click', () => dialog.close())
    // a click on the backdrop closes it, as Escape does
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close()
    })
  }

  // Handle the content block delete
  const initDelete = () => {
    const deleteForm = document.querySelector('#delete-content-block-form')
    const confirmModal = new Baton.Modal({
      title: deleteForm.dataset.modalTitle,
      content: deleteForm.dataset.modalContent,
      size: 'sm',
      actionBtnCb: () => {},
    })
    const deleteContentBlock = (action) => () => {
      deleteForm.action = action
      deleteForm.submit()
    }
    const deleteBtns = document.querySelectorAll('[data-toggle="delete-content-block"]')
    if (deleteBtns) {
      deleteBtns.forEach((btn) => {
        const contentDeleteUrl = btn.dataset.deleteUrl
        btn.addEventListener('click', (e) => {
          e.preventDefault()
          confirmModal.update({
            actionBtnLabel: deleteForm.dataset.modalButton,
            actionBtnCb: deleteContentBlock(contentDeleteUrl),
          })
          confirmModal.open()
        })
      })
    }
  }

  const buildPayload = (order) => {
    return { order: order.map((id, position) => ({ id, position })) }
  }

  // A message under the toolbar, read by the screen readers too
  const statusLine = document.getElementById('content-blocks-status')
  let statusTimer = null
  const showStatus = (message, isError) => {
    statusLine.textContent = message
    statusLine.classList.toggle('is-error', Boolean(isError))
    statusLine.classList.add('is-visible')
    clearTimeout(statusTimer)
    statusTimer = setTimeout(() => statusLine.classList.remove('is-visible'), isError ? 8000 : 2500)
  }

  const post = (url, body) =>
    fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : null,
    }).then((response) => (response.ok ? response.json() : Promise.reject(response.status)))

  const handleSavePosition = (payload) => {
    post(savePositionUrl, payload)
      .then(() => showStatus(form.dataset.savedMessage))
      .catch(() => showStatus(form.dataset.errorMessage, true))
  }

  // Show or hide a block on the page, from its switch
  const initToggle = () => {
    document.querySelectorAll('[data-toggle-url]').forEach((input) => {
      input.addEventListener('change', () => {
        const row = input.closest('.content-block')
        input.disabled = true
        post(input.dataset.toggleUrl)
          .then(({ enabled }) => {
            input.checked = enabled
            row.classList.toggle('is-disabled', !enabled)
            row.querySelector('.content-block-off').hidden = enabled
          })
          .catch(() => {
            input.checked = !input.checked
            showStatus(form.dataset.errorMessage, true)
          })
          .finally(() => {
            input.disabled = false
          })
      })
    })
  }

  // Copy a block: the copy comes right after it
  const initDuplicate = () => {
    const duplicateForm = document.getElementById('duplicate-content-block-form')
    document.querySelectorAll('[data-toggle="duplicate-content-block"]').forEach((button) => {
      button.addEventListener('click', () => {
        duplicateForm.action = button.dataset.duplicateUrl
        duplicateForm.submit()
      })
    })
  }

  const initSortable = () => {
    const list = document.querySelector('#content-blocks-list')
    if (!list) return
    const sortable = new Sortable(list, {
      handle: '.content-block-drag-handle',
      animation: 150,
      swapThreshold: 0.65,
      easing: 'cubic-bezier(1, 0, 0, 1)',
      store: {
        /**
         * Save the order of elements. Called onEnd (when the item is dropped).
         * @param {Sortable}  sortable
         */
        set: function (sortable) {
          const order = sortable.toArray()
          const payload = buildPayload(order)
          handleSavePosition(payload)
          // the "+" before the first block stays on the first block
          const before = list.querySelector('.content-block-insert.is-before')
          if (before) list.firstElementChild.appendChild(before)
        },
      },
    })
  }

  initAdd()
  initDelete()
  initToggle()
  initDuplicate()
  initSortable()
})(Baton.jQuery)
