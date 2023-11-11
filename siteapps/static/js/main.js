// Widget for category selection
// Modified example from here - https://recogito.github.io/guides/editor-widgets/
// This is a second order function that takes a list of categories and returns a category selection widget
function createCategoryWidget(categories, speciesVotes){
    return function(args) {
        // 1. Find the current class in the annotation, if any
        let currentClassBody = args.annotation ?
          args.annotation.bodies.find(function(b) {
            return b.purpose == 'classifying';
          }) : null;

        // 2. Keep the value in a variable
        let currentClassValue = currentClassBody ? currentClassBody.value : null;
        let currentClassConfidence = currentClassBody ? currentClassBody.confidence : null;
        let currentUpdateStatus = currentClassBody ? currentClassBody.updated : false;

        // 3. Triggers callbacks on user action
        let addTag = function(evt) {
          if (currentClassBody) {
            args.onUpdateBody(currentClassBody, {
              type: 'TextualBody',
              purpose: 'classifying',
              value: evt.target.dataset.tag,
              confidence: 1.0,
              updated: true
            });
          } else {
            args.onAppendBody({
              type: 'TextualBody',
              purpose: 'classifying',
              value: evt.target.dataset.tag,
              confidence: 1.0,
              updated: true
            });
          }
        }

        // 4. This part renders the UI elements
        // Render the classes as clickable buttons
        let createButton = function(value) {
          let button = document.createElement('button');
          button.className = 'btn btn-light align-items-center m-1 btn-tag';
          if (value == currentClassValue)
            button.className = 'btn btn-primary align-items-center m-1 btn-tag selected';
          // Set the tag value & the text content
          button.dataset.tag = value;
          button.textContent = value;
          // Add an event listener to update the class on click
          button.addEventListener('click', addTag);


          button.addEventListener('click', function () {
                // Focus the ok button if a selection is made.
              const okButton = $('button.r6o-btn:contains("Ok")');
              if (okButton.length) {
                  okButton['0'].focus({preventScroll: true});
              }

              // Restart the observer when menu is closed (for handling recent tags auto-selection)
              if (typeof observer !== "undefined") {
                  okButton.on('click', function () {
                      observer.observe(document, { attributes: false, childList: true, characterData: false, subtree: true });
                  });

                  const cancelButton = $('button.r6o-btn:contains("Cancel")');
                  cancelButton.on('click', function () {
                      observer.observe(document, { attributes: false, childList: true, characterData: false, subtree: true });
                  });
              }
          });

          if(categories.length > 5){
            let col = document.createElement("div")
            col.className = 'col-3 p-0 m-0 d-flex';

            if (recentTags.includes(`${button.textContent}`)) {
                col.innerHTML += `${col.innerHTML}<span style="position:absolute; font-size: 8px;" class="badge rounded-pill bg-dark"><text style="font-size: 8px">Recent Tag</text></span>`
            }
            else if (speciesVotes.includes(`${button.textContent}`)) {
                col.innerHTML += `${col.innerHTML}<span style="position:absolute; font-size: 8px;" class="badge rounded-pill bg-secondary"><text style="font-size: 8px">Has Vote In Image</text></span>`
              }

            col.appendChild(button);
            return col;
          }
          else {
            return button;
          }
        }

        let createStatusElement = function() {
          // Create display element
          let displayText = document.createElement('div');
          displayText.className = 'selected-display-text pt-3';
          // If a selection exists, display it else display a message

          if (currentClassValue) {
            if (currentUpdateStatus) {
                displayText.innerHTML = `<em>Classified as <b> ${currentClassValue} </b></em>`;
            }
            else {
                displayText.innerHTML = `<em>Classified as: <b> ${currentClassValue} </b><br/>Confidence: <b>${currentClassConfidence}</b></em>`;
            }
          } else {
            displayText.innerHTML = "<em>Select the type of object and click save</em>";
          }
          return displayText;
        }

        // Render the entire widget
        let container = document.createElement('div');
        if (categories.length > 5) {
            container.className = 'category-widget m-2 p-2 row';
        }
        else {
            container.className = 'category-widget m-2 p-2';
        }

        for (const category of categories) {
            let categoryButton = createButton(category);

            container.appendChild(categoryButton);

            // Get button for recent tag for this bbox
            if (typeof bboxes !== "undefined" && typeof recentTags !== "undefined") {
                const index = bboxes.findIndex(bbox => bbox.id == args.annotation.id);

                if (index != -1) {
                    let tag = recentTags[index];

                    if (category == tag) {
                        categoryButton.setAttribute("id", "recent-tag-div");
                    }
                }
            }
        }
        container.appendChild(createStatusElement())

        return container;
      }
}


/* Create a wrapper to render annotations & the widget for a given image element
 Annotations a list of objects created that look like this
  {
    "id": "701ade3e-6efd-4e2d-9b4f-6471f1a075ee",
    "class": "animal",
    "x": 0.00035992,
    "y": 0.41679,
    "w": 0.024461,
    "h": 0.063281,
  }
*/
function renderBoundingBoxes(imageElementID, annotations, widgets, config) {
    // Initialize a megadetector annotation widget
    let anno = Annotorious.init({
        image: imageElementID,
        widgets: widgets,
        fragmentUnit: 'percent',
        ...config
    });
    // Load each passed annotation
    for (const annotation of annotations) {
        anno.addAnnotation(
            {
                "@context": "http://www.w3.org/ns/anno.jsonld",
                "id": annotation.id,
                "type": "Annotation",
                "body": [{
                    "type": "TextualBody",
                    "purpose": "classifying",
                    "value": annotation.category,
                    "confidence": annotation.confidence
                }],
                "target": {
                    "selector": {
                    "type": "FragmentSelector",
                    "conformsTo": "http://www.w3.org/TR/media-frags/",
                    "value": `xywh=percent:${annotation.x*100},${annotation.y*100},${annotation.w*100},${annotation.h*100}`,
                    }
                }
            }
        );
    }
    // Return the annotation object to be used by the caller
    return anno
  }


// Function to consume an annoatation object, a container element and
// create a list of preview images from the original image
const uniqueColors = ["red", "orange", "lightgreen", "lightsteelblue", "cyan", "mediumpurple", "pink"]
function renderBoundingBoxPreviews(imageElementID, previewContainerID, anno) {
    let imageElement = document.getElementById(imageElementID);
    let previewContainer = document.getElementById(previewContainerID);

    previewContainer.innerHTML = ""

    let boxNum = 1;

    $(document).unbind("keydown");

    $(function () {
        $('[data-toggle="tooltip"]').tooltip('dispose');
        $(`.tooltip`).remove();
    })

    function checkNoAnnotations() {
        if ($("[id^='preview-']").length == 0) {
            previewContainer.innerHTML = `<h1 class="display-6"><i class="bi bi-bounding-box-circles"></i>&nbsp;&nbsp;<small><i>(No annotations found on image.)</i></small></text><br>`;
        }
    }

    function appendToast(cleanedId, type, messageHtml) {
        $(`.toast.hide`).remove();

        $(".toast-container").append(`
        <small>
            <div id="toast-${type}-${cleanedId}"
                    class="toast align-items-center fade"
                    role="alert" aria-live="assertive"
                    aria-atomic="true"
            >
                <div class="d-flex">
                    <div class="toast-body">
                        ${messageHtml}
                    </div>
                </div>
            </div>
        </small>`)

        $(document).ready(function () {
            $(`#toast-${type}-${cleanedId}`).toast('show');
        });
    }

    for (const annotation of anno.getAnnotations()) {
        let annotationText = annotation.body[0].value && annotation.body[0].value != 'unannotated' ? annotation.body[0].value : "(No Annotation)";
        let highlight = annotationText == "(No Annotation)" ? `style="background-color: #FFCCCB"` : "";
        const confidence = annotation.body[0].confidence && annotation.body[0].confidence !== 1 ? ` | <em>conf: ${annotation.body[0].confidence}</em></text>` : ``;

        // Remove the pound sign to work with Jquery
        const cleanedId = annotation.id.replace("#", "");
        const boxColor = uniqueColors[(boxNum - 1) % uniqueColors.length];

        // Setup the basic card
        let annotationHtml = `<div id="preview-${cleanedId}" class="card p-0 mb-3" style="outline-width: 8px; outline-style: groove; outline-color: ${boxColor}">
            <div class="card-body m-0 fw-bold">
                <button id="hide-${cleanedId}" class="border-0 bg-transparent"><i class="bi bi-eye"></i></button>
                <button id="delete-${cleanedId}" class="border-0 bg-transparent"><i class="bi bi-trash text-danger"></i></button>
                <span ${highlight} id="preview-label-${cleanedId}"> ${annotationText}${confidence}</span>
            </div>
        </div>`

        $(`#${previewContainerID}`).append(annotationHtml);

        const preview = $(`#preview-${cleanedId}`);
        const rectAnnotation = $(`[data-id='${annotation.id}']`);

        let innerRect = rectAnnotation.find(".a9s-inner");
        innerRect.addClass(`${boxColor}`);
        // Show tooltips on submit button hover
        innerRect.attr("data-toggle", "tooltip")
            .attr("title", annotationText)
            .addClass("preSubmitTooltip");

        $(`#save_annotations`).hover(
            function () {
                $('.preSubmitTooltip').tooltip('show');
            },
            function () {
                $('.preSubmitTooltip').tooltip('hide');
            }
        )

        timeout = null;

        // Highlighting the preview on hover
        preview.hover(
            function () {
                $(this).css("background-color", "rgba(255, 255, 0, 0.5)");
                innerRect.css("fill", "rgba(255, 255, 0, 0.2)")
            },
            function () {
                $(this).css("background-color", "rgba(255, 255, 255, 1.0)");
                innerRect.css("fill", "transparent")
            }
        );

        innerRect.hover(
            function () {
                preview.css("background-color", "rgba(255, 255, 0, 0.5)")

                // Use backspace to delete box when hovered
                $(document).keydown(function (event) {
                    if (event.keyCode === 8) {
                        event.preventDefault();
                        anno.removeAnnotation(annotation.id);
                        preview.remove();
                        checkNoAnnotations();

                        $(`.tooltip`).remove();

                        appendToast(cleanedId, "delete", `<kbd><i class="bi bi-trash"></i>&nbsp;BACKSPACE</kbd>&nbsp;&nbsp;Deleted box '${annotationText}.'</i>`)
                        $(document).unbind("keydown");
                    }
                });
            },
            function () {
                preview.css("background-color", "rgba(255, 255, 0, 0.0)")
                $(this).css("background-color", "transparent")
                $(document).unbind("keydown");
            }
        )

        // Right click hides the bbox
        innerRect.mousedown(function (event) {
            switch (event.which) {
                case 3:
                    hide();
                    appendToast(cleanedId, "hide", `<kbd><i class="bi bi-eye-slash"></i>&nbsp;(<i class="bi bi-mouse"> RIGHTCLICK</i>)</kbd>&nbsp;&nbsp;Hid box '${annotationText}.'</i>`)
                    break;
            }
        })


        // Handle visual changes for hiding bboxes
        const hide = function (speed = 300) {
            const eyeIcon = preview.find(".bi");
            if (!innerRect.hasClass('box-hidden')) {
                eyeIcon.removeClass("bi-eye").addClass("bi-eye-slash");
                innerRect.removeClass("preSubmitTooltip")
                innerRect.addClass('box-hidden');
                hiddenBoxes.add(cleanedId);
            }
            else {
                eyeIcon.removeClass("bi-eye-slash").addClass("bi-eye");
                innerRect.addClass("preSubmitTooltip")
                innerRect.removeClass('box-hidden');
                hiddenBoxes.delete(cleanedId);
            }
            innerRect.toggle(speed = speed);
            rectAnnotation.find(".a9s-outer").toggle(speed = speed);
        };

        hideButton = $(`#hide-${cleanedId}`);
        hideButton.click(hide);

        hideButton.on('persistHide', function () {
            hide(0);
        });

        $(`#delete-${cleanedId}`).click(function () {
            anno.removeAnnotation(annotation.id);
            preview.remove();

            checkNoAnnotations();
        });

        // Get the bounding box for the annotation
        let x, y, w, h;
        [x, y, w, h] = annotation.target.selector.value.split(':')[1].split(',').map(function (x) { return parseFloat(x).toFixed(5) });
        [x, y, w, h] = [x * 0.01 * imageElement.naturalWidth, y * 0.01 * imageElement.naturalHeight, w * 0.01 * imageElement.naturalWidth, h * 0.01 * imageElement.naturalHeight].map(Math.round)

        // Next, create a canvas element & add to the column
        let canvas = document.createElement('canvas');
        let context = canvas.getContext("2d");
        canvas.id = 'canvas-' + cleanedId;
        canvas.width = 250;
        canvas.style.maxWidth = '100%';
        canvas.height = canvas.width;

        // Calculate height of destination canvas to maintain aspect ratio
        let dx, dy, dw, dh;
        if (w > h) {
            dx = 0;
            dy = 0;
            dw = canvas.width;
            dh = Math.round(h * (dw / w));
        } else {
            dy = 0;
            dh = canvas.width;
            dw = Math.round(w * (dh / h));
            dx = Math.round((canvas.width - dw) / 2);
        }

        context.drawImage(imageElement, x, y, w, h, dx, dy, dw, dh);

        // Open the annotation widget when the label is clicked
        previewLabel = $(`#preview-label-${cleanedId}`);
        previewLabel.click(function () {
            anno.selectAnnotation(annotation.id);
        })

        previewLabel.attr("data-toggle", "tooltip")
            .attr("title", "Click To Annotate");

        // Show the previews in the staff annotation overview modal as well.
        try {
            let canvasClone = canvas.cloneNode();
            canvasClone.id = `canvas-clone-${annotation.id}`;
            let cloneContext = canvasClone.getContext("2d");
            cloneContext.drawImage(imageElement, x, y, w, h, dx, dy, dw, dh);
            $(`#staff-modal-card-${annotation.id}`).empty();
            $(`#staff-modal-card-${annotation.id}`).append(canvasClone);
        }
        catch {

        }

        boxNum++;
    }

    checkNoAnnotations();

    // Hide the previously hidden boxes after each re-render
    for (hiddenBoxId of hiddenBoxes) {
        $(`#hide-${hiddenBoxId}`).trigger("persistHide");
    }

    $(function () {
        $('[data-toggle="tooltip"]').tooltip();
    })
}
