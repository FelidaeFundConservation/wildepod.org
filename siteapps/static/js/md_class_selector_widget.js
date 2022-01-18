// Widget to select a MegaDetector class
// Modified example from here - https://recogito.github.io/guides/editor-widgets/
var MDClassSelectorWidget = function(args) {
    // 1. Find the current class in the annotation, if any
    var currentClassBody = args.annotation ?
      args.annotation.bodies.find(function(b) {
        return b.purpose == 'classifying';
      }) : null;

    // 2. Keep the value in a variable
    var currentClassValue = currentClassBody ? currentClassBody.value : null;

    // 3. Triggers callbacks on user action
    var addTag = function(evt) {
      if (currentClassBody) {
        args.onUpdateBody(currentClassBody, {
          type: 'TextualBody',
          purpose: 'classifying',
          value: evt.target.dataset.tag
        });
      } else {
        args.onAppendBody({
          type: 'TextualBody',
          purpose: 'classifying',
          value: evt.target.dataset.tag
        });
      }
    }

    // 4. This part renders the UI elements
    // Render the classes as clickable buttons
    var createButton = function(value) {
      var button = document.createElement('button');
      button.className = 'btn btn-light btn-mdclassselector mx-1';
      if (value == currentClassValue)
        button.className = 'btn btn-dark btn-mdclassselector mx-1 selected';
      // Set the tag value & the text content
      button.dataset.tag = value;
      button.textContent = value;
      // Add an event listener to update the class on click
      button.addEventListener('click', addTag);
      return button;
    }

    var createStatusElement = function() {
      // Create display element
      var displayText = document.createElement('div');
      displayText.className = 'selected-display-text pt-3';
      // If a selection exists, display it else display a message
      if (currentClassBody) {
        displayText.innerHTML = "<em>Selected object type: <b>" + currentClassValue + "</b></em>";
      } else {
        displayText.innerHTML = "<em>Select the type of object and click save</em>";
      }
      return displayText;
    }

    // Render the entire widget
    var container = document.createElement('div');
    container.className = 'mdclass-widget py-2';

    var animalButton = createButton('animal');
    var personButton = createButton('person');
    var vehicleButton = createButton('vehicle');

    // Render the current selection if any as text
    container.appendChild(animalButton);
    container.appendChild(personButton);
    container.appendChild(vehicleButton);
    container.appendChild(createStatusElement())

    return container;
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
function renderAnnotations(imageElementID, annotations, readOnly=false) {
  // Initialize a megadetector annotation widget
  var anno = Annotorious.init({
      image: imageElementID,
      widgets: [
          MDClassSelectorWidget,
      ],
      fragmentUnit: 'percent',
      readOnly: readOnly
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
                  "value": annotation.class,
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
