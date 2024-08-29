
reannotateUrl = `${$('meta[name="django-vars"]').attr('reannotate-url')}`;

 // If an annotator made a mistake, they can return to a previous image
 function promptReturnToPreviousImage(imageId) {
    if (confirm("Are you sure you want to return to re-annotate this previous image?") == true) {
        savePreviousImageToReturnTo(imageId)
    }
}

// Save image to return to
function savePreviousImageToReturnTo(imageId) {
    return new Promise(function(resolve, reject) {
        const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;
        let data = {
            'csrfmiddlewaretoken': csrftoken,
            'returnToImageId': imageId,
        }

        $.ajax({
            url: reannotateUrl,
            method: 'POST',
            data: data,
            dataType: 'json',
            success: function(data) {
                window.location.reload();
            }
        });
    });
}
