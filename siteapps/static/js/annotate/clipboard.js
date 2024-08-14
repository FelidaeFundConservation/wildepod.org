
imageId = `${$('meta[name="django-vars"]').attr('image-id')}`;

async function copyImageID() {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(`https://wildepod.org/images/image/${imageId}`).then(function () {
            alert("Link copied to clipboard. Please provide this information to staff if there's an issue.");
        }).catch(function (error) {
            console.error("Clipboard access denied or error: ", error)
            alert("Copy failed. Please check that clipboard permissions are enabled.");
        })
    }
    else {
        alert("Clipboard API is not supported in this browser.");
    }
}
