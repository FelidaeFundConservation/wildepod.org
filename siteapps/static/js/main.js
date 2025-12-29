// Widget for category selection
// Modified example from here - https://recogito.github.io/guides/editor-widgets/
// This is a second order function that takes a list of categories and returns a category selection widget
function createCategoryWidget(widgetData, pipeline) {
    widgetData = JSON.parse(widgetData)

    return function (args) {
        // 1. Find the current class in the annotation, if any
        let currentClassBody = args.annotation ?
            args.annotation.bodies.find(function (b) {
                return b.purpose == 'classifying';
            }) : null;

        // 2. Keep the value in a variable
        let currentClassValue = currentClassBody ? currentClassBody.value : null;
        let currentClassConfidence = currentClassBody ? currentClassBody.confidence : null;
        let currentUpdateStatus = currentClassBody ? currentClassBody.updated : false;

        // 3. Triggers callbacks on user action
        let addTag = function (evt) {
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
        let createButton = function (data, multiColumn) {
            let selected = data.name == currentClassValue ? "btn-primary" : "btn-light";
            let colClass = multiColumn ? 'col-3' : 'col-12'

            let badge = typeof recentTags !== 'undefined' && recentTags.includes(data.name) ? `
                <span style="position:absolute; font-size: 8px;"
                      class="badge rounded-pill bg-dark"
                >
                    <text style="font-size: 8px">Recent Tag</text>
                </span>` : "";

            badge = (badge == "" && data.has_vote) ? `
                <span style="position:absolute; font-size: 8px;"
                      class="badge rounded-pill bg-secondary"
                >
                      <text style="font-size: 8px">Has Vote In Image</text>
                </span>` : badge;

            let color = "";

            if (data.ai_detection) {
                badge = `
                <span style="position:absolute; font-size: 8px; pointer-events: none; background-color: #3d8ed1"
                      class="badge rounded-pill"
                >
                      <text class="text-white" style="font-size: 8px">Computer Vision Suggestion</text>
                </span>`;
                color = `style="border: 2px solid #3d8ed1;"`
            }

            let buttonHtml = `
                <div class="${colClass} p-0 m-0 d-flex position-relative">
                    <button class="btn ${selected} align-items-center m-1 btn-tag" data-tag="${data.name}" ${color}>
                        ${data.name}
                    </button>
                    ${badge}
                </div>`;

            return buttonHtml;
        }

        // Render the entire widget
        let displayTextHtml = "";

        if (currentClassValue) {
            if (currentUpdateStatus) {
                displayTextHtml = `<em>Classified as <b> <mark>${currentClassValue}</mark> </b></em>`;
            }
            else {
                displayTextHtml = `<em>Classified as: <b> <mark>${currentClassValue}</mark> </b><br/>Confidence: <b>${currentClassConfidence}</b></em>`;
            }
        }
        else {
            displayTextHtml = "<em>Select the type of object and click save</em>";
        }

        const row = "row"

        let container = document.createElement("div");

        // Show species for person, animal, and vehicle in separate tabs
        categoryTabsHtml = pipeline == "species" ? `
            <nav>
                <div class="nav nav-tabs p-3" id="nav-tab" role="tablist">
                    ${Object.entries(widgetData).map((keyValueTuple) => {
                        const key = keyValueTuple[0]
                        const value = keyValueTuple[1]

                        const tabSelected = (
                            !currentClassValue && value["open"])
                            || Object.values(value["data"]).some(
                                subgroup => subgroup["items"].some(
                                    item => item.name === currentClassValue
                                )
                        ) ? "show active" : "";
                        return `
                        <a class="nav-link d-none d-sm-inline ${tabSelected}"
                            id="nav-${key}-tab"
                            data-bs-toggle="tab"
                            href="#nav-${key}"
                            role="tab"
                            aria-controls="nav-${key}"
                            aria-selected="false">
                            <text class="small">
                                ${key.charAt(0).toUpperCase() + key.slice(1).toLowerCase()}
                            </text>
                        </a>`;
                    }).join('')}
                </div>
            </nav>
            <nav id="nav-menu">
                <div class="tab-content p-3">
                  ${Object.entries(widgetData).map(keyValueTuple => {
                    const key = keyValueTuple[0]
                    const value = keyValueTuple[1]
                    const tabSelected = (
                            !currentClassValue && value["open"])
                            || Object.values(value["data"]).some(
                                subgroup => subgroup["items"].some(
                                    item => item.name === currentClassValue
                                )
                        ) ? "show active" : "";
                    return `
                    <div class="tab-pane fade p-0 text-center ${tabSelected}"
                        id="nav-${key}"
                        role="tabpanel"
                        aria-labelledby="nav-${key}-tab"
                        style="max-height: 75vh; overflow-y: auto;">
                        ${
                            Object.entries(widgetData[key]["data"]).map(([key, values]) => {
                                const hexKey = "C" + [...key]
                                    .map(char => char.charCodeAt(0).toString(16).padStart(2, '0'))
                                    .join('');
                                return key != "null" ? `
                                <div class="accordion" id="${hexKey}-accordion">
                                    <div class="accordion-item">
                                        <h2 class="accordion-header" id="${hexKey}-header">
                                        <button class="accordion-button collapsed"
                                                type="button"
                                                data-bs-toggle="collapse"
                                                data-bs-target="#${hexKey}-collapse"
                                                aria-expanded="false"
                                                aria-controls="${hexKey}-collapse"
                                        >
                                            ${key}
                                        </button>
                                        </h2>
                                        <div id="${hexKey}-collapse"
                                            class="accordion-collapse collapse ${(values["open"] || values["items"].some(value => value['name'] === currentClassValue)) && "show"}"
                                            aria-labelledby="${hexKey}-collapse"
                                            data-bs-parent="#${hexKey}-accordion"
                                        >
                                        <div id="${hexKey}-list" class="accordion-body m-2 p-2 row">
                                            ${values["items"].map((value) => {
                                                return createButton(value, values["items"].length > 3)
                                            }).join('')}
                                        </div>
                                        </div>
                                    </div>
                                </div>
                                ` : `
                                <div id="${hexKey}-list" class="m-2 p-2 row">
                                ${values["items"].map((value) => {
                                        return createButton(value, values["items"].length > 3)
                                    }).join('')}
                                </div>
                                `
                            }).join('')
                        }
                    </div>
                    `
                  }).join('')}
                </div>
            </nav>` : "";

        container.innerHTML = `${categoryTabsHtml}`;


        container.addEventListener('click', function (event) {
            if (event.target.classList.contains('btn-tag')) {
                addTag(event);
            }
        });

        $(`.tooltip`).remove();

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
    // Create formatter function before initialization
    const formatter = function(annotation) {
        console.log('Formatter called for:', annotation.id);
        // The annotation ID from Annotorious includes a # prefix, so we need to match both ways
        const cleanId = annotation.id.replace('#', '');
        const annotationData = annotations.find(a => a.id === annotation.id || a.id === cleanId);

        if (annotationData && annotationData.speciesnetName) {
            // Format confidence as percentage (rounded to nearest integer)
            const confidencePercent = Math.round(annotationData.speciesnetConfidence * 100);
            const label = `${annotationData.speciesnetName} (${confidencePercent}%)`;
            console.log('Returning label:', label);
            return label;
        }
        return null; // No label for other boxes
    };

    // Initialize with formatter if ShapeLabelsFormatter is available
    let initConfig = {
        image: imageElementID,
        widgets: widgets,
        fragmentUnit: 'percent',
        ...config
    };

    // Add formatter to config if available
    if (typeof Annotorious.ShapeLabelsFormatter !== 'undefined') {
        initConfig.formatter = Annotorious.ShapeLabelsFormatter(formatter);
    }

    let anno = Annotorious.init(initConfig);

    // Load each passed annotation
    for (const annotation of annotations) {
        const annotationBody = {
            "@context": "http://www.w3.org/ns/anno.jsonld",
            "id": annotation.id,
            "type": "Annotation",
            "body": [{
                "type": "TextualBody",
                "purpose": "classifying",
                "category": annotation.categoryType,
                "value": annotation.category,
                "confidence": annotation.confidence
            }],
            "target": {
                "selector": {
                    "type": "FragmentSelector",
                    "conformsTo": "http://www.w3.org/TR/media-frags/",
                    "value": `xywh=percent:${annotation.x * 100},${annotation.y * 100},${annotation.w * 100},${annotation.h * 100}`,
                }
            }
        };

        // Add SpeciesNet prediction as a tag for the shape-labels plugin to display
        if (annotation.speciesnetName) {
            const confidencePercent = Math.round(annotation.speciesnetConfidence * 100);
            const aiPrediction = `ai: ${annotation.speciesnetName} (${confidencePercent}%)`;
            let labelValue;

            // Check if user has annotated this bbox
            if (annotation.userSpeciesAnnotation && annotation.userSpeciesAnnotation.trim() !== '') {
                const userSpecies = annotation.userSpeciesAnnotation.trim();
                const aiSpecies = annotation.speciesnetName.trim();

                if (userSpecies.toLowerCase() === aiSpecies.toLowerCase()) {
                    // User confirmed AI prediction - add checkmark
                    labelValue = `${aiPrediction} ✓`;
                } else {
                    // User corrected AI prediction - strikethrough AI and show correction
                    labelValue = `<del>${aiPrediction}</del> ${userSpecies}`;
                }
            } else {
                // No user annotation yet - just show AI prediction
                labelValue = aiPrediction;
            }

            annotationBody.body.push({
                "type": "TextualBody",
                "purpose": "tagging",
                "value": labelValue
            });
        }

        anno.addAnnotation(annotationBody);
    }
    // Return the annotation object to be used by the caller
    return anno
}


// Function to consume an annoatation object, a container element and
// create a list of preview images from the original image
const uniqueColors = ["red", "orange", "lightgreen", "lightsteelblue", "cyan", "mediumpurple", "pink"]
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

function checkNoAnnotations() {
    let annotationPreviewContainer = $(`#annotations-preview`);
    let bboxesPreviewContainer = $(`#bboxes-preview`);

    if ($("[class^='preview-']").length == 0) {
        annotationPreviewContainer.html(`<h6 class="display-6 small"><i class="bi bi-bounding-box-circles"></i>&nbsp;&nbsp;<i>(No annotations found on image.)</i></text><br>`);
        bboxesPreviewContainer.html(`<h5 class="display-5"><i class="bi bi-bounding-box-circles"></i>&nbsp;&nbsp;<i>(No annotations found on image.)</i></text><br>`);
    }
}

function updateAnnotationCount() {
    $(`#annotations-card-header`).text(`Annotations (${anno.getAnnotations().length})`)
}

function renderBoundingBoxPreviews(imageElementID, anno) {
    let imageElement = document.getElementById(imageElementID);

    let annotationPreviewContainer = $(`#annotations-preview`);
    let bboxesPreviewContainer = $(`#bboxes-preview`);

    bboxesPreviewContainer.empty();
    annotationPreviewContainer.empty()

    let boxNum = 1;

    $('[data-toggle="tooltip"]').tooltip('dispose');
    $(`.tooltip`).remove();

    displayOverlappingPairs(anno, imageElement);

    const sortAnnotations = anno.getAnnotations()
    sortAnnotations.sort((a, b) => b.body[0].confidence - a.body[0].confidence);

    for (const annotation of sortAnnotations) {
        if (annotation.type !== "Annotation") continue;

        let annotationText = annotation.body[0].value && annotation.body[0].value != 'unannotated' ? annotation.body[0].value : "(No Annotation)";
        let highlight = annotationText == "(No Annotation)" ? `style="background-color: #FFCCCB"` : "";

        // Remove the pound sign to work with Jquery
        const cleanedId = annotation.id.replace("#", "");
        const boxColor = uniqueColors[(boxNum - 1) % uniqueColors.length];

        let categoryIcon = "";
        let category = annotation.body[0].category;

        if (category == "person") {
            categoryIcon = `<i class="bi bi-person-fill"></i>`;
        }
        else if (category == "vehicle") {
            categoryIcon = `<i class="bi bi-car-front-fill"></i>`;
        }
        else if (category == "animal") {
            categoryIcon = `<i class="fa-solid fa-paw"></i>`;
        }

        const confidence = annotation.body[0].confidence && annotation.body[0].confidence !== 1 ? ` | <em>conf: ${annotation.body[0].confidence}</em></text>` : ``;

        // Setup the basic card
        let annotationHtml = `<div class="preview-${cleanedId} preview-lite card p-0 mb-3" style="outline-width: 8px; outline-style: groove; outline-color: ${boxColor}">
            <div class="card-body m-0 fw-bold">
                <button class="hide-${cleanedId} border-0 bg-transparent"><i class="bi bi-eye"></i></button>
                <button class="delete-${cleanedId} border-0 bg-transparent"><i class="bi bi-trash text-danger"></i></button>
                <span ${highlight} class="annotation-label-${cleanedId} small">&nbsp;&nbsp;${categoryIcon}&nbsp;&nbsp;${annotationText}${confidence}&nbsp;&nbsp;&nbsp;</span>
            </div>
        </div>`

        annotationPreviewContainer.append(annotationHtml);

        // Setup the bbox preview card
        let bboxHtml = `<div class="preview-${cleanedId} card p-0 m-2" style="width: 250px; outline-width: 8px; outline-style: groove; outline-color: ${boxColor}">
        <div class="card-header py-2">
            <text class="annotation-label-${cleanedId} my-0 py-0" ${highlight}><i class="bi bi-eye"></i>&nbsp;&nbsp;<b>${annotationText}</b>${confidence}
            </div>
            <div id="bbox-preview-body-${cleanedId}" class="card-body">
            </div>
            <div class="card-footer text-muted border-bottom">Box ${boxNum}</div>
            <div class="btn-group" role="group">
                <button class="hide-${cleanedId} btn btn-outline-secondary w-50 m-0 border-0 bg-light">Hide Box</button>
                <button class="delete-${cleanedId} btn btn-outline-danger w-50 m-0 border-0 bg-light">Delete Box</button>
            </div>
        </div>`

        $(`#bboxes-preview`).append(bboxHtml);

        const preview = $(`.preview-${cleanedId}`);
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
        setRectHighlight(annotation.id, preview, backgroundColor = true);

        innerRect.hover(
            function () {
                preview.css("background-color", "rgba(255, 255, 0, 0.5)")
                hoveredAnnotation = annotation;
            },
            function () {
                preview.css("background-color", "rgba(255, 255, 0, 0.0)")
                $(this).css("background-color", "transparent")

                hoveredAnnotation = null;
            }
        )

        innerRect.mousedown(function (event) {
            switch (event.which) {
                // Right click hides the bbox
                case 3:
                    hide();
                    appendToast(cleanedId, "hide", `<kbd><i class="bi bi-eye-slash"></i>&nbsp;(<i class="bi bi-mouse"> RIGHTCLICK</i>)</kbd>&nbsp;&nbsp;Hid box '${annotationText}.'</i>`)
                    break;

            }
        })


        // Handle visual changes for hiding bboxes
        const hide = function (speed = 300) {
            $(`.tooltip`).remove();
            const eyeIcon = preview.find(".bi");

            if (!preview.hasClass("bbox-hidden")) {
                eyeIcon.removeClass("bi-eye").addClass("bi-eye-slash");
                innerRect.removeClass("preSubmitTooltip");
                rectAnnotation.hide(speed = speed);
                preview.addClass("bbox-hidden");
                preview.addClass("opacity-50");
            }
            else {
                eyeIcon.removeClass("bi-eye-slash").addClass("bi-eye");
                innerRect.addClass("preSubmitTooltip");
                rectAnnotation.show(speed = speed);
                preview.removeClass("bbox-hidden");
                preview.removeClass("opacity-50");
            }

            hiddenBoxes = $(`.bbox-hidden:not(.preview-lite)`);
        };

        hideButton = $(`.hide-${cleanedId}`);
        hideButton.click(hide);

        hideButton.on('persistHide', function () {
            hide(0);
        });

        $(`.delete-${cleanedId}`).click(function () {
            userHasDeletedBox = true;
            showBboxWarningMsg();

            anno.removeAnnotation(annotation.id);
            preview.remove();
            updateAnnotationCount();

            checkNoAnnotations();
        });

        let canvas = createMaintainedAspectRatioCanvas(annotation, cleanedId, imageElement);
        $(`#bbox-preview-body-${cleanedId}`).append(canvas);

        // Open the annotation widget when the label is clicked
        previewLabel = $(`.annotation-label-${cleanedId}`);
        previewLabel.click(function () {
            anno.selectAnnotation(annotation.id);
        })

        previewLabel.attr("data-toggle", "tooltip")
            .attr("title", "Click To Annotate");

        // Show the previews in the staff annotation overview modal as well.
        let canvasClone = createMaintainedAspectRatioCanvas(annotation, `-clone-${cleanedId}`, imageElement);
        $(`#staff-modal-card-${annotation.id}`).empty();
        $(`#staff-modal-card-${annotation.id}`).append(canvasClone);


        boxNum++;

        showBboxWarningMsg();
    }

    checkNoAnnotations();
    updateAnnotationCount();

    // Hide the previously hidden boxes after each re-render
    reHideBboxes();
    adjustImage();
    $(function () {
        $('[data-toggle="tooltip"]').tooltip();
    })
}

function setRectHighlight(annotationId, element, backgroundColor = false) {
    const rectAnnotation = $(`[data-id='${annotationId}']`);
    let innerRect = rectAnnotation.find(".a9s-inner");

    function hover() {
        if (backgroundColor) {
            $(this).css("background-color", "rgba(255, 255, 0, 0.5)");
        }
        innerRect.css("fill", "rgba(255, 255, 0, 0.2)")
    }

    function unhover() {
        if (backgroundColor) {
            $(this).css("background-color", "rgba(255, 255, 255, 1.0)");
        }
        innerRect.css("fill", "transparent")
    }


    $(element).hover(hover, unhover);
}

function reHideBboxes(fade = false) {
    for (box of hiddenBoxes) {
        let id = $(box).attr("class").split(" ")[0].replace("preview-", "");

        if (fade) {
            $(`.hide-${id}`).first().trigger("click");
        } else {
            $(`.hide-${id}`).first().trigger("persistHide");
        }
    }
}

function createMaintainedAspectRatioCanvas(annotation, cleanedId, imageElement) {
    // Box was deleted
    if (!imageElement) return

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
        dw = canvas.width;
        dh = Math.round(h * (dw / w));
        dy = canvas.height / 2 - dh / 2;
    } else {
        dy = 0;
        dh = canvas.width;
        dw = Math.round(w * (dh / h));
        dx = Math.round((canvas.width - dw) / 2);
    }
    context.drawImage(imageElement, x, y, w, h, dx, dy, dw, dh);

    canvas.style.backdropFilter = "brightness(0%)";

    return canvas;
}

// Detect bounding boxes pair with a high percentage overlap.
// User can confirm if pairings are unique or duplicates
const overlapThreshold = 0.55;
function getOverlappingBboxes(anno) {
    let annotations = anno.getAnnotations();
    const uniqueOverlappingPairings = new Set();


    for (let firstIndex = 0; firstIndex < annotations.length; firstIndex++) {
        for (let secondIndex = firstIndex + 1; secondIndex < annotations.length; secondIndex++) {
            var [bbox1X1, bbox1Y1, bbox1W, bbox1H] = annotations[firstIndex].target.selector.value.split(":")[1].split(",");
            var [bbox2X1, bbox2Y1, bbox2W, bbox2H] = annotations[secondIndex].target.selector.value.split(":")[1].split(",");

            // Get the ending x and y coord of each bbox
            let bbox1X2 = parseFloat(bbox1X1) + parseFloat(bbox1W);
            let bbox1Y2 = parseFloat(bbox1Y1) + parseFloat(bbox1H);
            let bbox2X2 = parseFloat(bbox2X1) + parseFloat(bbox2W);
            let bbox2Y2 = parseFloat(bbox2Y1) + parseFloat(bbox2H);

            // Calculate points of overlapping area
            let overlapX1 = Math.max(bbox1X1, bbox2X1);
            let overlapY1 = Math.max(bbox1Y1, bbox2Y1);
            let overlapX2 = Math.min(bbox1X2, bbox2X2);
            let overlapY2 = Math.min(bbox1Y2, bbox2Y2);

            // Calculate area of bboxes
            let overlapWidth = overlapX2 - overlapX1;
            let overlapHeight = overlapY2 - overlapY1;

            if (overlapWidth > 0 && overlapHeight > 0) {
                overlapArea = overlapWidth * overlapHeight;

                let bbox1Area = parseFloat(bbox1W) * parseFloat(bbox1H);
                let bbox2Area = parseFloat(bbox2W) * parseFloat(bbox2H);

                let bbox1OverlapPercentage = overlapArea / bbox1Area;
                let bbox2OverlapPercentage = overlapArea / bbox2Area;

                let maxOverlap = Math.max(bbox1OverlapPercentage, bbox2OverlapPercentage);

                if (maxOverlap >= overlapThreshold) {
                    uniqueOverlappingPairings.add([[annotations[firstIndex], annotations[secondIndex]], maxOverlap]);
                }
            }
        }
    }
    return uniqueOverlappingPairings;
}


// Show overlapping bboxes for user to check if they're the same subject
function displayOverlappingPairs(anno, imageElement) {
    const uniqueOverlappingPairings = getOverlappingBboxes(anno);
    const container = $(`#deduplicate-bboxes`);
    container.empty();

    let count = 1;

    const noDuplicatesTextHtml = `<h6 class="small"><i class="bi bi-check"></i>&nbsp;&nbsp;No overlapping boxes with similarity >${Math.round(overlapThreshold * 100)}% found.</h6>`;

    if (uniqueOverlappingPairings.size > 0) {
        for (pairing of uniqueOverlappingPairings) {
            let overlapPercentage = Math.round(pairing[1] * 100);

            let cleanedId1 = pairing[0][0].id.replace("#", "");
            let cleanedId2 = pairing[0][1].id.replace("#", "");

            const canvas1 = createMaintainedAspectRatioCanvas(pairing[0][0], `duplicate-check-${cleanedId1}-${count}`, imageElement);
            const canvas2 = createMaintainedAspectRatioCanvas(pairing[0][1], `duplicate-check-${cleanedId2}-${count}`, imageElement);

            const duplicateEntryHtml = `<div id="duplicate-compare-${count}" data-first=${cleanedId1} data-second=${cleanedId2} class="card w-100 mt-0 p-0 mb-3">
                <div class="card-header">${overlapPercentage}% Overlap</div>
                <div class="card-body">
                    <div id="duplicate-canvases-${count}" class="row"></div>
                </div>
                <div class="card-footer py-2">
                    <div id="duplicate-delete-${count}" class="row"></div>
                </div>
            </div>`

            container.append(duplicateEntryHtml);

            let entryCanvasSection = $(`#duplicate-canvases-${count}`);
            entryCanvasSection.append(canvas1);
            entryCanvasSection.append(canvas2);

            $(canvas1).addClass("w-50");
            $(canvas2).addClass("w-50");

            let entryDeleteSection = $(`#duplicate-delete-${count}`);

            let deleteButton1 = `<div class="col-6"><button class="btn btn-outline-danger w-50 remove-duplicate" data-target="${pairing[0][0].id}">Delete Box</button></div>`
            let deleteButton2 = `<div class="col-6"><button class="btn btn-outline-danger w-50 remove-duplicate" data-target="${pairing[0][1].id}">Delete Box</button></div>`

            entryDeleteSection.append(deleteButton1);
            entryDeleteSection.append(deleteButton2);

            setRectHighlight(pairing[0][0].id, canvas1, backgroundColor = false);
            setRectHighlight(pairing[0][1].id, canvas2, backgroundColor = false);

            count++;
        }

        // Set the delete event handlers
        function clearElements() {
            updateAnnotationCount();

            if (container.children().length == 0) {
                container.append(noDuplicatesTextHtml);
            }
            renderBoundingBoxPreviews(imageElement.id, anno);
        }

        $(`.remove-duplicate`).each(function () {
            setRectHighlight($(this).attr("data-target"), $(this), backgroundColor = false);
        })
        $(`.remove-duplicate`).click(function () {
            anno.removeAnnotation($(this).attr("data-target"));
            clearElements();
        });
    }
    else {
        container.append(noDuplicatesTextHtml);
    }
}
