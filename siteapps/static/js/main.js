// Widget for category selection
// Modified example from here - https://recogito.github.io/guides/editor-widgets/
// This is a second order function that takes a list of categories and returns a category selection widget
function createCategoryWidget(categories){
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
                  okButton['0'].focus({ preventScroll: true });
              }

              // Restart the observer when menu is closed (for handling recent tags auto-selection)
              if (typeof observer !== "undefined") {
                  okButton.on('click', function () {
                      observer.observe(document, { attributes: false, childList: true, characterData: false, subtree: true });
                  });
              }
          });

          if(categories.length > 5){
            let col = document.createElement("div")
            col.className = 'col-3 p-0 m-0 d-flex';
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
                        let recentTagDiv = document.createElement('div');
                        recentTagDiv.setAttribute("id", "recent-tag-div");
                        let recentTagLabel = document.createElement('h5');

                        recentTagLabel.textContent = "Recent Tag"

                        Object.assign(recentTagDiv.style, {
                            display: 'flex',
                            justifyContent: 'center',
                        });

                        recentTagDiv.append(categoryButton);

                        let hr = document.createElement('hr');
                        hr.style.margin = '10px';

                        container.prepend(hr);
                        container.prepend(recentTagDiv);
                        container.prepend(recentTagLabel);
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


function createImageBboxActions(imageElementID, previewContainerID, anno) {
    let bboxNum = 1;
    $("#bbox-actions").empty();
    $(".tooltip").tooltip('dispose');

    for (const annotation of anno.getAnnotations()) {

        // Create the in-image bbox actions menu.
        const isUnannotated = annotation.body[0].value === "unannotated" || !annotation.body[0].value;

        // New bboxes contain a # symbol, doesn't work with JQuery.
        const replacedAnnotationId = annotation.id.replace('#', '');

        let annotationName = !isUnannotated ? annotation.body[0].value : "(No Annotation)";
        let titleString = `Box ${bboxNum} - ${annotationName}`;
        titleString = titleString.length > 21 ? titleString.slice(0, 18) + "..." : titleString;
        let backgroundColor = !isUnannotated ? "white" : "red"

        bboxEntryHtml = `<button id="label-${replacedAnnotationId}"
                            style="color: ${backgroundColor}; background-color: gray; border: 1px solid black;"
                        >&nbsp;&nbsp;<i class="bi bi-eye"></i>&nbsp;&nbsp;${titleString}
                        <button id="delete-${replacedAnnotationId}" style="border: 1px solid transparent; background-color: transparent;"><i class="bi bi-trash"></i>
                        </button>
                        </button>`
        $("#bbox-actions").append(bboxEntryHtml);
        bboxNum++;

        let bboxPreview = $(`[data-id='${annotation.id}']`)

        bboxPreview.attr("data-toggle", "tooltip");
        bboxPreview.attr("data-bs-placement", "bottom");
        bboxPreview.attr("title", annotationName);
        bboxPreview.tooltip('show');

        const label = $(`#label-${replacedAnnotationId}`);
        label.css("font-weight", "bold");
        const rect = bboxPreview.find(".a9s-outer");

        bboxPreview.hover(function () {
            label.css("background-color", "rgba(255, 255, 0, 0.6)");
        }, function () {
            label.css("background-color", "gray");
        })

        label.click(function () {
            $(".a9s-outer").tooltip('hide');
            bboxPreview.toggle();

            if (bboxPreview.css("display") == "none") {
                label.html(label.html().replace("bi-eye", "bi-eye-slash"));
                label.css("color", "lightgray");
                label.css("font-style", "italic");
                label.css("font-weight", "normal");
            }
            else {
                label.html(label.html().replace("bi-eye-slash", "bi-eye"));
                label.css("color", backgroundColor);
                label.css("font-style", "normal");
                label.css("font-weight", "bold");
            }

            assignDeleteButtonListeners()
        })

        function assignDeleteButtonListeners() {
            const deleteButton = $(`#delete-${replacedAnnotationId}`);

            deleteButton.click(function () {
                $(".a9s-annotation").show();
                anno.removeAnnotation(annotation.id);
                createImageBboxActions(imageElementID, previewContainerID, anno);
                //renderBoundingBoxPreviews(imageElementID, previewContainerID, anno);
                //createBboxActions();
            })

            deleteButton.hover(function () {
                deleteButton.css("color", "red");
            }, function () {
                deleteButton.css("color", "black");
            })
        } (assignDeleteButtonListeners());


        label.hover(function () {
            if (bboxPreview.css("display") != "none") {
                label.css("background-color", "rgba(255, 255, 0, 0.6)");
                rect.css("fill", "rgba(255, 255, 0, 0.2)");
                bboxPreview.tooltip('show');
            }
        }, function () {
            label.css("background-color", "gray");
            rect.css("fill", "rgba(0, 0, 0, 0.0)");
            bboxPreview.tooltip('hide');
        })
    }

    if ($("#bbox-actions").children().length === 0) {
        $("#bbox-actions").text("(No annotations found on image.)").css("color", "white");
    }

    $('[data-toggle="tooltip"]').tooltip();
    $('[data-toggle="tooltip"]').tooltip('show');

    if (window.tooltipTimeout) {
        window.clearTimeout(tooltipTimeout);
    }
    window.tooltipTimeout = setTimeout(function () {
        $('[data-toggle="tooltip"]').tooltip('hide');
    }, 5000);
}

  // Function to consume an annoatation object, a container element and
  // create a list of preview images from the original image
function renderBoundingBoxPreviews(imageElementID, previewContainerID, anno) {

    let imageElement = document.getElementById(imageElementID);
    let previewContainer = document.getElementById(previewContainerID);

    previewContainer.innerHTML = ""

    for (const annotation of anno.getAnnotations()) {
        // Get the bounding box for the annotation
        let x, y, w, h;

        [x, y, w, h] = annotation.target.selector.value.split(':')[1].split(',').map(function (x) { return parseFloat(x).toFixed(5) });
        [x, y, w, h] = [x*0.01*imageElement.naturalWidth, y*0.01*imageElement.naturalHeight, w*0.01*imageElement.naturalWidth, h*0.01*imageElement.naturalHeight].map(Math.round)

        // Create a column container for each annotation
        let col = document.createElement('div');
        col.className = 'col-6 col-md-4 col-lg-3 col-xl-2 m-2';
        col.id = 'preview-col-' + annotation.id;
        // Add the column to the container first
        previewContainer.appendChild(col)

        // Create the label element & add to the column
        let label = document.createElement('div');
        label.className = 'preview-label py-2';
        label.id = 'preview-label-' + annotation.id;
        let confidence = annotation.body[0].confidence ? annotation.body[0].confidence : 1.0;
        label.innerHTML = `<text id="annotation-text-${annotation.id}" class="my-0 py-0"><b>${annotation.body[0].value}</b> |  <em>conf: ${confidence}</em></text>`;
        if (annotation.body[0].value && annotation.body[0].value != 'unannotated'){
        col.appendChild(label);
        }

        // Next, create a canvas element & add to the column
        let canvas = document.createElement('canvas');
        let context = canvas.getContext("2d");
        canvas.id = 'canvas-' + annotation.id;
        canvas.width = col.offsetWidth;
        canvas.style.maxWidth = '100%';
        canvas.height = col.offsetWidth;

        // Calculate height of destination canvas to maintain aspect ratio
        let dx, dy, dw, dh;
        if (w > h) {
        dx = 0;
        dy = 0;
        dw = col.offsetWidth;
        dh = Math.round(h * (dw / w));
        } else {
        dy = 0;
        dh = col.offsetWidth;
        dw = Math.round(w * (dh / h));
        dx = Math.round((col.offsetWidth - dw) / 2);
        }

        context.drawImage(imageElement, x, y, w, h, dx, dy, dw, dh);
        col.appendChild(canvas);

        // Show the previews in the staff annotation overview modal as well.
        try {
            let canvasClone = canvas.cloneNode();
            canvasClone.id = 'canvas-clone-' + annotation.id;
           let cloneContext = canvasClone.getContext("2d");
            cloneContext.drawImage(imageElement, x, y, w, h, dx, dy, dw, dh);
            document.getElementById(`staff-modal-card-${annotation.id}`).appendChild(canvasClone);
        }
        catch {

        }
    }
}
