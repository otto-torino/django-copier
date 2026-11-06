;(function ($) {
  const form = document.getElementById('changelist-form')
  const savePositionUrl = form.dataset.savePositionUrl
  const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value

  // Use the same Baton modal as the changelist columns and filters.
  const initAdd = () => {
    const template = document.getElementById('add-block-template')
    const modal = new Baton.Modal({
      title: template.dataset.title,
      content: template.innerHTML,
      hideFooter: true,
    })
    const dialog = modal.modalObj[0]
    dialog.setAttribute('tabindex', '-1')
    dialog.setAttribute('aria-labelledby', 'add-block-title')
    dialog.querySelector('.modal-title').id = 'add-block-title'
    const note = dialog.querySelector('[data-insert-note]')
    let trigger = null
    const open = (button) => {
      trigger = button
      const after = button.dataset.after || ''
      dialog.querySelectorAll('[data-add-url]').forEach((link) => {
        link.href = link.dataset.addUrl + (after ? '&after=' + encodeURIComponent(after) : '')
      })
      if (after === 'start') {
        note.textContent = template.dataset.startMessage
      } else if (after) {
        note.textContent = template.dataset.afterMessage.replace('%(name)s', button.dataset.afterName)
      }
      note.hidden = !after
      modal.open()
    }
    document.querySelectorAll('[data-add-block]').forEach((button) => {
      button.addEventListener('click', () => open(button))
    })
    dialog.addEventListener('hidden.bs.modal', () => {
      trigger?.focus()
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

  // The outcome as a message of the admin, where Baton moves them, after
  // the title, so that it looks as the others: one message, updated by the
  // next change
  const showStatus = (message, isError) => {
    let list = document.querySelector('#content > .messagelist')
    if (!list) {
      list = document.createElement('ul')
      list.className = 'messagelist'
      const title = document.querySelector('#content > h1')
      if (title) title.after(list)
      else document.getElementById('content-main').before(list)
    }
    let item = list.querySelector('[data-contents-status]')
    if (!item) {
      item = document.createElement('li')
      item.dataset.contentsStatus = ''
      item.setAttribute('role', 'status')
      list.append(item)
    }
    item.className = isError ? 'error' : 'success'
    item.textContent = message
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
