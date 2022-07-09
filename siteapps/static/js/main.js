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
          button.className = 'btn btn-light m-1';
          if (value == currentClassValue)
            button.className = 'btn btn-primary m-1 selected';
          // Set the tag value & the text content
          button.dataset.tag = value;
          button.textContent = value;
          // Add an event listener to update the class on click
          button.addEventListener('click', addTag);
          return button;
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
        container.className = 'category-widget py-2';

        for(const category of categories){
            let categoryButton = createButton(category);
            container.appendChild(categoryButton);
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
      // Add the column to the container first
      previewContainer.appendChild(col)

      // Create the label element & add to the column
      let label = document.createElement('div');
      label.className = 'preview-label py-2';
      let confidence = annotation.body[0].confidence ? annotation.body[0].confidence : 1.0;
      label.innerHTML = `<p class="my-0 py-0"><b>${annotation.body[0].value}</b> |  <em>conf: ${confidence}</em></p>`;
      if (annotation.body[0].value){
        col.appendChild(label);
      }

      // Next, create a canvas element & add to the column
      let canvas = document.createElement('canvas');
      let context = canvas.getContext("2d");
      canvas.id = 'canvas-' + annotation.id;
      canvas.width = col.offsetWidth;
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
    }
  }
