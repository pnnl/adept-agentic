#!/usr/bin/env nextflow

nextflow.enable.dsl=2

// Define parameters
params.repo_url = ""           // GitHub repository URL
params.output_dir = "./results"  // Directory to store the scan results
params.enable_debug = "" // Enable debug mode for more verbose output
params.output_file = "gitxray_report.json" // Default output file name for the scan results
params.output_format = "json" // Default output format for gitxray


// Log parameters
log.info """
         -----------------------------------------
         G I T X R A Y   S C A N N I N G   P I P E L I N E
         -----------------------------------------
         Repository URL  : ${params.repo_url}
         Output directory: ${params.output_dir}
         Debug mode      : ${params.enable_debug ? 'Enabled' : 'Disabled'}
         Output file     : ${params.output_file}
         Output format   : ${params.output_format}
         -----------------------------------------
         """

// Check if the repository URL is provided
if (!params.repo_url) {
    exit 1, "[Nextflow Pipeline Error] Repository URL not specified. Please use --repo_url <repository_url>."
}

process run_gitxray {
    tag "Scanning ${params.repo_url}"
    publishDir params.output_dir, mode: 'copy', overwrite: true

    input:
    val repo_url

    output:
    path params.output_file

    script:
    """
    gitxray --repository "${repo_url}" --output-format "${params.output_format}" --outfile "${params.output_file}" ${params.enable_debug ? '--debug' : ''}
    """
}

workflow {
    repo_channel = Channel.of(params.repo_url)
    run_gitxray(repo_channel)
}