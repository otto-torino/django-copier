/* global django */
django.jQuery(function ($) {
  $(".cabinet-inline-wrap").each(function () {
    var wrap = $(this)
    wrap
      .find("input[type='file']")
      .attr("disabled", !wrap.find(".cabinet-inline-upload select").val())
  })

  $(document.body).on("change", ".cabinet-inline-upload select", function () {
    var wrap = $(this).closest(".cabinet-inline-wrap")
    wrap.find("input[type='file']").attr("disabled", !this.value)
  })

  $(document.body).on("change", ".cabinet-inline-upload input", function (e) {
    doUpload($(this).closest(".cabinet-inline-wrap"), e.target.files[0])
  })

  // The lookup popup only sets the id and triggers "change": fetch the name.
  $(document.body).on("change", ".cabinet-inline-field input", function () {
    var wrap = $(this).closest(".cabinet-inline-wrap")
    var pk = parseInt(this.value, 10)
    if (!pk) {
      showFile(wrap, null)
      return
    }
    $.getJSON(wrap.data("info-url").replace(/\/0\/info\/$/, "/" + pk + "/info/"))
      .done(function (data) {
        showFile(wrap, data)
      })
      .fail(function () {
        showFile(wrap, null)
      })
  })

  $(document.body).on("click", ".cabinet-inline-clear", function () {
    var wrap = $(this).closest(".cabinet-inline-wrap")
    wrap.find(".cabinet-inline-field input").val("")
    showFile(wrap, null)
  })

  function showFile(wrap, data) {
    wrap
      .find(".cabinet-inline-link")
      .text(data ? data.name : "")
      .attr("href", data ? data.url : "")
      .prop("hidden", !data)
    wrap.find(".cabinet-inline-empty").prop("hidden", !!data)
    wrap.find(".cabinet-inline-clear").prop("hidden", !data)
    wrap
      .find(".cabinet-inline-thumb")
      .attr("src", (data && data.image_url) || "")
      .prop("hidden", !(data && data.image_url))
  }

  function doUpload(wrap, file) {
    var d = new FormData()
    d.append("csrfmiddlewaretoken", $("input[name=csrfmiddlewaretoken]").val())
    d.append("folder", wrap.find("select").val())
    d.append("file", file)

    $.ajax({
      url: wrap.data("url"),
      type: "POST",
      data: d,
      contentType: false, // request
      processData: false, // request
      dataType: "json", // response
      success: function (data) {
        wrap.find(".cabinet-inline-field input").val(data.pk)
        wrap.find(".cabinet-inline-upload input").val("")
        showFile(wrap, data)
      },
    })
  }
})
