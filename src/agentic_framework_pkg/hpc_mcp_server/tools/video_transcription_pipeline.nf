#!/usr/bin/env nextflow
nextflow.enable.dsl=2

params.video_input = false // URL or local file path
params.outdir = "./transcription_results" // Default output directory for Nextflow
params.whisper_model = "base" // e.g., tiny, base, small, medium, large
params.output_audio_format = "mp3" // Audio format for whisper

log.info """
    ----------------------------------------------------
    V I D E O   T R A N S C R I P T I O N   P I P E L I N E
    ----------------------------------------------------
    Video Input      : ${params.video_input}
    Output Directory : ${params.outdir}
    Whisper Model    : ${params.whisper_model}
    Audio Format     : ${params.output_audio_format}
    Work Directory   : ${workflow.workDir}
    ----------------------------------------------------
    """

if (!params.video_input) {
    exit 1, "[Nextflow Pipeline Error] Video input (URL or file path) not specified. Please use --video_input <input>."
}

process download_audio {
    tag "DownloadAudio: ${params.video_input}"
    // Publish to a subdirectory within the main outdir specified by the Python tool
    publishDir "${params.outdir}/audio", mode: 'copy', overwrite: true

    input:
    val video_source // The video URL or path

    output:
    path "downloaded_audio.${params.output_audio_format}", emit: audio_file

    script:
    // yt-dlp handles both URLs and local file paths.
    // -x extracts audio. --audio-format specifies the desired audio format.
    // -o specifies the output filename template.
    """
    yt-dlp -x --audio-format ${params.output_audio_format} -o "downloaded_audio.%(ext)s" "${video_source}"
    """
}

process transcribe_audio {
    tag "TranscribeAudio: ${audio.name} with ${params.whisper_model} model"
    publishDir "${params.outdir}/transcripts", mode: 'copy', overwrite: true

    input:
    path audio // The downloaded audio file

    output:
    path "*.txt", emit: transcript_txt // We primarily care about the .txt for summarization
    path "*.json", emit: transcript_json // Whisper can also output JSON
    path "*.srt", emit: transcript_srt   // and SRT
    path "*.vtt", emit: transcript_vtt   // and VTT

    script:
    """
    whisper "${audio}" --model ${params.whisper_model} --output_dir . --language en
    """
}

workflow {
    download_audio(params.video_input)
    transcribe_audio(download_audio.out.audio_file)
}